"""TemporaSMS API client (SMS-Activate-compatible handler_api.php).

Powers the three product panels:
    * WhatsApp Account panel
    * TG Number Change panel
    * All Apps OTP panel (service = selected app slug)

IMPORTANT
---------
TemporaSMS does NOT expose REST paths like ``/api/countries``.  Its whole API
is a single endpoint::

    https://api.temporasms.com/stubs/handler_api.php?api_key=...&action=...

with ``action`` in {getBalance, getCountries, getServices, getPrices,
getPricesV2, getPricesV3, getNumber, getNumberV2, getStatus, setStatus}.

The old client only tried REST paths, so every panel showed "0 countries" and
"no provider configured" even with a perfectly valid key.  This version speaks
the real protocol and normalises the (partly text, partly JSON) responses.

Environment:
    TEMPORASMS_API_KEY     -> your TemporaSMS API key (required)
    TEMPORASMS_BASE_URL    -> default https://api.temporasms.com
"""
import asyncio
import json
import time

import aiohttp

from config import (
    TEMPORASMS_API_KEY,
    TEMPORASMS_BASE_URL,
    logger,
)

_TIMEOUT = aiohttp.ClientTimeout(total=25)

# Cache the country catalogue for an hour (it rarely changes) and the price
# table for two minutes (stock moves quickly).
_COUNTRIES_CACHE = {"ts": 0.0, "data": []}
_COUNTRIES_TTL = 3600
_PRICES_CACHE = {}  # service -> {"ts": float, "data": dict}
_PRICES_TTL = 120
_SERVICES_CACHE = {"ts": 0.0, "data": []}
_SERVICES_TTL = 3600
_RESOLVED_SERVICE = {}  # requested name -> provider's real service code

# Full app names / slugs -> the short service codes the panel expects.
_SERVICE_ALIASES = {
    "telegram": "tg", "tg": "tg",
    "whatsapp": "wa", "wa": "wa",
    "instagram": "ig", "ig": "ig",
    "facebook": "fb", "fb": "fb",
    "twitter": "tw", "tw": "tw", "twitter/x": "tw", "x": "tw",
    "tiktok": "tt", "tt": "tt",
    "google": "go", "go": "go",
    "discord": "ds", "ds": "ds",
    "uber": "ub", "ub": "ub",
    "amazon": "am", "am": "am",
    "netflix": "nf", "nf": "nf",
    "paypal": "pp", "pp": "pp",
}


def configured() -> bool:
    return bool(TEMPORASMS_API_KEY)


def _headers():
    return {"Accept": "application/json, text/plain, */*"}


def _base_url() -> str:
    return (TEMPORASMS_BASE_URL or "https://api.temporasms.com").rstrip("/")


def _norm_service(service) -> str:
    s = str(service or "").strip().lower()
    return _SERVICE_ALIASES.get(s, s)


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _try_json(text):
    if not text:
        return None
    text = text.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


async def _call(action, **params):
    """GET handler_api.php?action=... Returns (text, error)."""
    if not configured():
        return None, "TEMPORASMS_API_KEY is not configured"
    url = f"{_base_url()}/stubs/handler_api.php"
    query = {"api_key": TEMPORASMS_API_KEY, "action": action}
    for k, v in params.items():
        if v is not None:
            query[k] = str(v)
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, params=query, headers=_headers()) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    return None, f"HTTP {resp.status}: {text[:160]}"
                return text, None
    except Exception as exc:
        logger.warning(f"TemporaSMS {action} failed: {exc}")
        return None, str(exc)


# --------------------------------------------------------------------------- #
#  Parsing helpers
# --------------------------------------------------------------------------- #
def _parse_countries(data):
    """Normalise getCountries into [{'id': str, 'name': str}]."""
    rows = []

    def walk(node, hint_id=None):
        if isinstance(node, dict):
            cid = node.get("id") or node.get("country_id") or hint_id
            name = (node.get("eng") or node.get("name") or node.get("country")
                    or node.get("title") or node.get("english"))
            if cid is not None and name:
                rows.append({"id": str(cid), "name": str(name)})
                return
            for k, v in node.items():
                # SMS-Activate style flat map: {"0": "Russia", "12": "Japan"}.
                if str(k).isdigit() and isinstance(v, str) and v.strip():
                    rows.append({"id": str(k), "name": v.strip()})
                    continue
                walk(v, str(k) if str(k).isdigit() else hint_id)
        elif isinstance(node, list):
            for item in node:
                walk(item, hint_id)

    walk(data)
    seen = {}
    for r in rows:
        seen[r["id"]] = r
    return list(seen.values())


def _parse_prices(data, service):
    """Extract {country_id: {'price': float|None, 'stock': int}} from a
    getPrices / getPricesV2 / getPricesV3 response."""
    out = {}
    svc = service.lower()

    def walk(node, cid=None):
        if isinstance(node, dict):
            keys_lower = {str(k).lower(): k for k in node.keys()}
            # Price leaf?
            if any(k in node for k in ("cost", "price", "amount")):
                leaf_cid = node.get("country") or node.get("country_id") or cid
                if leaf_cid is None:
                    return
                price = _num(node.get("cost", node.get("price", node.get("amount"))))
                stock = int(_num(
                    node.get("count", node.get("stock",
                             node.get("available", node.get("qty", 0)))), 0) or 0)
                prev = out.get(str(leaf_cid))
                if prev is None or (price and (prev["price"] is None or price < prev["price"])):
                    out[str(leaf_cid)] = {"price": price, "stock": stock}
                return
            # Service branch: when our service key is present, follow only it.
            if svc in keys_lower:
                walk(node[keys_lower[svc]], cid)
                return
            for k, v in node.items():
                walk(v, str(k) if str(k).isdigit() else cid)
        elif isinstance(node, list):
            for item in node:
                walk(item, cid)

    walk(data)
    return out


def _iso_for(name):
    try:
        from utils.country_search import resolve_country
        r = resolve_country(name)
        if r:
            return r.get("iso2")
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
async def get_balance():
    text, err = await _call("getBalance")
    if text is None:
        return {"ok": False, "error": err, "balance": 0.0, "currency": "INR"}
    text = text.strip()
    if text.startswith("ACCESS_BALANCE:"):
        return {"ok": True, "balance": _num(text.split(":", 1)[1], 0.0) or 0.0,
                "currency": "INR"}
    data = _try_json(text)
    if isinstance(data, dict):
        node = data.get("data") if isinstance(data.get("data"), dict) else data
        for key in ("balance", "amount", "wallet", "credit"):
            if key in node:
                return {"ok": True, "balance": _num(node[key], 0.0) or 0.0,
                        "currency": str(node.get("currency", "INR")).upper()}
    return {"ok": False, "error": text[:160] or "Unknown balance response",
            "balance": 0.0, "currency": "INR"}


async def get_services():
    text, err = await _call("getServices")
    if text is None:
        return {"ok": False, "error": err, "services": []}
    data = _try_json(text)
    services = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                slug = val.get("code") or val.get("slug") or val.get("service") or key
                name = val.get("name") or val.get("title") or slug
                services.append({"slug": str(slug), "name": str(name)})
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                slug = item.get("code") or item.get("slug") or item.get("service")
                name = item.get("name") or item.get("title") or slug
                if slug:
                    services.append({"slug": str(slug), "name": str(name)})
    if not services:
        return {"ok": False, "error": text[:160] or "No services returned",
                "services": []}
    return {"ok": True, "services": services}


async def _countries_map():
    """Cached [{'id','name'}] from getCountries."""
    now = time.time()
    if _COUNTRIES_CACHE["data"] and now - _COUNTRIES_CACHE["ts"] < _COUNTRIES_TTL:
        return _COUNTRIES_CACHE["data"]
    text, err = await _call("getCountries")
    data = _try_json(text) if text else None
    rows = _parse_countries(data) if data is not None else []
    if rows:
        _COUNTRIES_CACHE["data"] = rows
        _COUNTRIES_CACHE["ts"] = now
    return rows


async def _prices_for(service):
    """Cached {country_id: {'price','stock'}} for a service.

    The provider's service codes are not guaranteed to be the SMS-Activate
    short codes (``tg``/``wa``/...).  If we ask for prices with a code the
    panel does not know, it happily returns an empty table -- which used to
    make every panel render "countries with flags but 0 stock / no price".
    So we resolve the real code first and try every plausible spelling.
    """
    svc = _norm_service(service)
    now = time.time()
    cached = _PRICES_CACHE.get(svc)
    if cached and now - cached["ts"] < _PRICES_TTL and cached["data"]:
        return cached["data"]

    candidates = []
    for cand in (await _resolve_service(service), svc, str(service or "").strip().lower()):
        cand = str(cand or "").strip().lower()
        if cand and cand not in candidates:
            candidates.append(cand)

    merged = {}
    # getPrices is the classic, most widely supported action.
    for action in ("getPrices", "getPricesV2", "getPricesV3"):
        for cand in candidates:
            text, err = await _call(action, service=cand)
            data = _try_json(text) if text else None
            if data is None:
                continue
            parsed = _parse_prices(data, cand)
            for cid, info in parsed.items():
                prev = merged.get(cid)
                if prev is None or (info["price"] and
                                    (prev["price"] is None or info["price"] < prev["price"])):
                    merged[cid] = info
            if merged:
                break
        if merged:
            break
    if merged:
        _PRICES_CACHE[svc] = {"ts": now, "data": merged}
    return merged


async def _services_list():
    """Cached provider service catalogue: [{'slug','name'}]."""
    now = time.time()
    if _SERVICES_CACHE["data"] and now - _SERVICES_CACHE["ts"] < _SERVICES_TTL:
        return _SERVICES_CACHE["data"]
    text, err = await _call("getServices")
    data = _try_json(text) if text else None
    rows = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                slug = val.get("code") or val.get("slug") or val.get("service") or key
                name = val.get("name") or val.get("title") or slug
                rows.append({"slug": str(slug), "name": str(name)})
            elif isinstance(val, str):
                rows.append({"slug": str(key), "name": val})
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                slug = item.get("code") or item.get("slug") or item.get("service")
                name = item.get("name") or item.get("title") or slug
                if slug:
                    rows.append({"slug": str(slug), "name": str(name)})
    if rows:
        _SERVICES_CACHE["data"] = rows
        _SERVICES_CACHE["ts"] = now
    return rows


async def _resolve_service(service):
    """Map an app name/slug onto the provider's real service code.

    Order: exact alias -> exact slug -> name/slug containment -> alias.
    Never raises; always returns something usable.
    """
    raw = str(service or "").strip()
    if not raw:
        return ""
    key = raw.lower()
    if key in _RESOLVED_SERVICE:
        return _RESOLVED_SERVICE[key]

    alias = _norm_service(raw)
    resolved = None

    services = await _services_list()
    if services:
        by_slug = {str(s["slug"]).lower(): s["slug"] for s in services}
        # 1. exact slug match on the alias, then on the raw name
        for cand in (alias, key):
            if cand in by_slug:
                resolved = by_slug[cand]
                break
        # 2. exact name match
        if resolved is None:
            for s in services:
                if str(s["name"]).strip().lower() in (key, alias):
                    resolved = s["slug"]
                    break
        # 3. containment either way (e.g. "telegram" vs "Telegram (TG)")
        if resolved is None:
            for s in services:
                nm = str(s["name"]).strip().lower()
                sl = str(s["slug"]).strip().lower()
                if key and (key in nm or nm in key or key in sl):
                    resolved = s["slug"]
                    break

    if resolved is None:
        resolved = alias or key
    _RESOLVED_SERVICE[key] = resolved
    return resolved



async def get_countries(service: str):
    """Countries available for a service, with live price + stock per country.

    Returns ``{"ok": bool, "countries": [{code, name, price, stock, id}], "error"}``
    where ``code`` is an ISO-2 code (so the UI can show flags and the buy flow
    can round-trip it) and ``id`` is the provider's numeric country id.
    """
    if not configured():
        return {"ok": False, "error": "TEMPORASMS_API_KEY is not configured",
                "countries": []}
    svc = _norm_service(service)
    countries = await _countries_map()
    if not countries:
        return {"ok": False, "error": "Could not load country list from panel",
                "countries": []}

    prices = await _prices_for(svc)
    if not prices:
        # No price table at all means the service code was not understood by
        # the panel.  Returning 180 price-less rows is what made the UI look
        # like it was "only showing country flags", so report it honestly.
        return {
            "ok": False,
            "error": (f"Panel returned no prices for service '{svc}'. "
                      "Check the service code / that this app is sold on the panel."),
            "countries": [],
        }

    rows = []
    for c in countries:
        pid = c["id"]
        info = prices.get(pid) or {}
        iso = _iso_for(c["name"])
        rows.append({
            "code": iso or f"id{pid}",
            "name": c["name"],
            "price": info.get("price"),
            "stock": int(info.get("stock") or 0),
            "id": pid,
        })

    # Only show countries that actually have stock or a price (so the list is
    # real, not 180 empty rows).
    priced = [r for r in rows if r["price"] is not None or r["stock"] > 0]
    if priced:
        rows = priced
    else:
        return {
            "ok": False,
            "error": f"No country on the panel currently sells '{svc}'.",
            "countries": [],
        }

    best = {}
    for r in rows:
        prev = best.get(r["code"])
        if prev is None or (r["price"] is not None and
                            (prev["price"] is None or r["price"] < prev["price"])):
            best[r["code"]] = r
    ordered = sorted(best.values(),
                     key=lambda c: (c["price"] is None, c["price"] or 0, c["name"]))
    return {"ok": True, "countries": ordered}


async def _resolve_country_id(country):
    """Map any country identifier (ISO-2/ISO-3/name/numeric id) to the
    provider's numeric country id."""
    s = str(country or "").strip()
    if not s:
        return None
    if s.isdigit():
        return s
    if s.lower().startswith("id") and s[2:].isdigit():
        return s[2:]

    countries = await _countries_map()
    try:
        from utils.country_search import country_matches
    except Exception:
        country_matches = None

    for c in countries:
        iso = _iso_for(c["name"])
        if country_matches and iso and country_matches(s, iso, c["name"]):
            return c["id"]
    for c in countries:
        if s.lower() in c["name"].lower():
            return c["id"]
    return None


async def buy_number(service: str, country: str):
    """Request a number. Returns {ok, order_id, phone, provider, error}."""
    if not configured():
        return {"ok": False, "error": "TEMPORASMS_API_KEY is not configured",
                "order_id": None, "phone": None}
    svc = await _resolve_service(service)
    pid = await _resolve_country_id(country)
    if pid is None:
        return {"ok": False, "error": f"Unknown country '{country}' on panel",
                "order_id": None, "phone": None}

    # Preferred: getNumberV2 (JSON metadata).
    text, err = await _call("getNumberV2", service=svc, country=pid, type="best")
    if text:
        text = text.strip()
        data = _try_json(text)
        if isinstance(data, dict):
            node = data.get("data") if isinstance(data.get("data"), dict) else data
            oid = (node.get("id") or node.get("activationId")
                   or node.get("activation_id") or node.get("order_id"))
            phone = (node.get("phone") or node.get("phoneNumber")
                     or node.get("number") or node.get("msisdn"))
            if oid and phone:
                return {"ok": True, "order_id": str(oid), "phone": str(phone),
                        "provider": "temporasms", "raw": node, "error": None}
        if text.startswith("ACCESS_NUMBER:"):
            parts = text.split(":")
            if len(parts) >= 3:
                return {"ok": True, "order_id": parts[1], "phone": parts[2],
                        "provider": "temporasms", "error": None}
        if text and not text.startswith("STATUS_"):
            # A real provider error code (NO_BALANCE, BAD_SERVICE, ...).
            return {"ok": False, "error": text, "order_id": None, "phone": None}

    # Fallback: classic getNumber (text ACCESS_NUMBER:id:phone).
    text2, err2 = await _call("getNumber", service=svc, country=pid)
    if text2:
        text2 = text2.strip()
        if text2.startswith("ACCESS_NUMBER:"):
            parts = text2.split(":")
            if len(parts) >= 3:
                return {"ok": True, "order_id": parts[1], "phone": parts[2],
                        "provider": "temporasms", "error": None}
        return {"ok": False, "error": text2, "order_id": None, "phone": None}

    return {"ok": False, "error": err or err2 or "No number available",
            "order_id": None, "phone": None}


async def get_otp(order_id: str):
    """Poll for the SMS code. Returns {ok, otp, status, error}."""
    text, err = await _call("getStatus", id=order_id)
    if text is None:
        return {"ok": False, "otp": None, "status": "error", "error": err}
    text = text.strip()
    if text.startswith("STATUS_OK:"):
        return {"ok": True, "otp": text.split(":", 1)[1].strip(),
                "status": "received", "error": None}
    if text == "STATUS_WAIT_CODE" or text.startswith("STATUS_WAIT_RETRY"):
        return {"ok": False, "otp": None, "status": "waiting", "error": None}
    if text == "STATUS_CANCEL":
        return {"ok": False, "otp": None, "status": "cancelled", "error": None}
    data = _try_json(text)
    if isinstance(data, dict):
        node = data.get("data") if isinstance(data.get("data"), dict) else data
        otp = node.get("otp") or node.get("code") or node.get("sms_code")
        status = str(node.get("status", "waiting")).lower()
        if otp:
            return {"ok": True, "otp": str(otp), "status": "received", "error": None}
        return {"ok": False, "otp": None, "status": status, "error": None}
    return {"ok": False, "otp": None, "status": "waiting", "error": None}


async def cancel(order_id: str):
    """Cancel an activation (status=8). Returns {ok, error}."""
    text, err = await _call("setStatus", id=order_id, status="8")
    if text is None:
        return {"ok": False, "error": err}
    return {"ok": True, "error": None}


async def wait_for_otp(order_id: str, attempts: int = 20, delay: int = 6):
    """Poll until an OTP arrives or attempts run out."""
    for _ in range(max(1, attempts)):
        result = await get_otp(order_id)
        if result.get("otp"):
            return result
        if result.get("status") in ("cancelled", "canceled", "expired", "refunded"):
            return result
        await asyncio.sleep(delay)
    return {"ok": False, "otp": None, "status": "timeout",
            "error": "No SMS received in time"}


# Curated fallback country list used only when the live API is unreachable so
# the panel UI still renders.
FALLBACK_COUNTRIES = [
    ("us", "United States"), ("in", "India"), ("gb", "United Kingdom"),
    ("id", "Indonesia"), ("ph", "Philippines"), ("vn", "Vietnam"),
    ("ca", "Canada"), ("ua", "Ukraine"), ("kz", "Kazakhstan"),
    ("br", "Brazil"), ("ru", "Russia"), ("de", "Germany"), ("fr", "France"),
    ("es", "Spain"), ("it", "Italy"), ("mx", "Mexico"), ("ng", "Nigeria"),
    ("ke", "Kenya"), ("pk", "Pakistan"), ("bd", "Bangladesh"), ("np", "Nepal"),
    ("lk", "Sri Lanka"), ("ae", "UAE"), ("sa", "Saudi Arabia"),
    ("tr", "Turkey"), ("eg", "Egypt"), ("za", "South Africa"),
    ("au", "Australia"), ("my", "Malaysia"), ("th", "Thailand"),
]


def fallback_countries():
    return [{"code": c, "name": n, "price": None, "stock": 0}
            for c, n in FALLBACK_COUNTRIES]
