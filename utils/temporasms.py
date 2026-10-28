"""TemporaSMS API client (SMS-Activate-compatible ``handler_api.php``).

Powers the three product panels:
    * WhatsApp Account panel
    * TG Number Change panel
    * All Apps OTP panel (service = selected app slug)

THE PROTOCOL, AS VERIFIED LIVE
------------------------------
TemporaSMS exposes a single endpoint::

    https://api.temporasms.com/stubs/handler_api.php?api_key=...&action=...

with ``action`` in {getBalance, getOperators, getCountries, getServices,
getPrices, getPricesV2, getPricesV3, getNumber, getNumberV2, getStatus,
setStatus}.

Four things the old client got wrong, each of which made every panel show
"0 countries" with a perfectly valid key:

1. ``operator`` is a **required** parameter for ``getCountries``,
   ``getServices`` and every ``getPrices*`` call.  Without it the panel
   answers ``BAD_OPERATOR`` -- which the old code reported as "no prices".
2. **Service codes are per-operator.**  ``telegram`` is ``tvm`` and
   ``whatsapp`` is ``wqp``, and they only exist in operator **13**'s
   catalogue (1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15, 16 are the public
   routes).  Asking operator 1 for ``tg`` returns ``BAD_SERVICE``.  So the
   client resolves the code *and* the operator from the merged catalogues.
3. ``getPrices*`` needs ``service`` **and** ``country`` **and**
   ``operator``; there is no "all countries" call (``country=all`` and
   ``country=0`` both answer ``BAD_COUNTRY``).  A country sweep is required,
   so it is done concurrently and cached.
4. Errors are JSON, not text: ``{"success": false, "errorCode":
   "NO_BALANCE", "message": ...}``.  ``NO_BALANCE`` must be surfaced as
   "top up the panel wallet", not as a generic failure.

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

_TIMEOUT = aiohttp.ClientTimeout(total=30)
_SWEEP_TIMEOUT = aiohttp.ClientTimeout(total=25)

# Public routes advertised by ``action=getOperators``.
_OPERATORS = [1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15, 16]
# Operator 13 is the only route that sells Telegram (tvm) and WhatsApp (wqp).
_PREFERRED_OPERATOR = 13
# How many price lookups to run in parallel during a country sweep.
_SWEEP_CONCURRENCY = 20

# Cache the country catalogue for an hour (it rarely changes) and the price
# table for three minutes (stock moves quickly).
_COUNTRIES_CACHE = {}   # operator -> {"ts": float, "data": {id: name}}
_COUNTRIES_TTL = 3600
_PRICES_CACHE = {}      # service -> {"ts": float, "data": dict}
_PRICES_TTL = 180
_CATALOGUE = {"ts": 0.0, "data": {}}
_CATALOGUE_TTL = 3600
_RESOLVED_SERVICE = {}  # requested name -> (code, operator)

# Full app names / slugs -> canonical provider service *names*.
_SERVICE_ALIASES = {
    "telegram": "telegram", "tg": "telegram",
    "whatsapp": "whatsapp", "wa": "whatsapp",
    "instagram": "instagram", "ig": "instagram",
    "facebook": "facebook", "fb": "facebook",
    "twitter": "twitter", "tw": "twitter", "twitter/x": "twitter",
    "x": "twitter",
    "tiktok": "tiktok", "tt": "tiktok",
    "google": "google", "go": "google",
    "discord": "discord", "ds": "discord",
    "uber": "uber", "ub": "uber",
    "amazon": "amazon", "am": "amazon",
    "netflix": "netflix", "nf": "netflix",
    "paypal": "paypal", "pp": "paypal",
    "signal": "signal",
    "snapchat": "snapchat",
    "linkedin": "linkedin",
    "yahoo": "yahoo",
    "microsoft": "microsoft",
    "apple": "apple",
    "openai": "openai",
    "chatgpt": "openai",
}


def configured() -> bool:
    return bool(TEMPORASMS_API_KEY)


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


def _error_code(text):
    """Return the provider's ``errorCode`` for a JSON error payload."""
    data = _try_json(text)
    if isinstance(data, dict) and data.get("success") is False:
        return str(data.get("errorCode") or data.get("error") or "ERROR")
    # Classic actions answer with a bare token such as ``NO_BALANCE``.  Success
    # tokens (``ACCESS_NUMBER:...``, ``ACCESS_CANCEL``) and status tokens
    # (``STATUS_WAIT_CODE``) must NOT be mistaken for errors.
    if isinstance(text, str):
        token = text.strip()
        if (token and token.isupper() and len(token) < 40 and " " not in token
                and ":" not in token
                and not token.startswith(("ACCESS_", "STATUS_"))):
            return token
    return None


def friendly_error(text):
    """Turn a raw provider answer into something a buyer can act on."""
    code = _error_code(text)
    if not code:
        return None
    code = code.upper()
    mapping = {
        "NO_BALANCE": (
            "The OTP panel wallet is empty. Please ask the admin to top up "
            "the TemporaSMS balance and try again."
        ),
        "BAD_SERVICE": (
            "The panel does not sell this app on the selected route. "
            "Please pick another app or country."
        ),
        "BAD_COUNTRY": "The panel does not have this country right now.",
        "BAD_OPERATOR": "The panel route is unavailable. Please try again.",
        "NO_NUMBERS": "No number is available for this app/country. Try another country.",
        "NO_NUMBER": "No number is available for this app/country. Try another country.",
        "BAD_KEY": "The TemporaSMS API key is invalid. Ask the admin to update it.",
        "BAD_ACTION": "The panel rejected the request. Please try again.",
        "USER_BANNED": "The TemporaSMS account is banned. Contact the panel.",
        "TOO_MANY_REQUESTS": "The panel is rate-limiting us. Please wait a moment.",
        "UNDER_DEVELOPMENT": "This panel feature is under maintenance.",
        "WRONG_MAX_PRICE": "No number within the allowed price. Try another country.",
        "NO_ACTIVATION": "That order has expired on the panel.",
    }
    return mapping.get(code, f"Panel error: {code}")


async def _call(action, operator=None, **params):
    """GET ``handler_api.php?action=...``. Returns ``(text, error)``."""
    if not configured():
        return None, "TEMPORASMS_API_KEY is not configured"
    url = f"{_base_url()}/stubs/handler_api.php"
    query = {"api_key": TEMPORASMS_API_KEY, "action": action}
    if operator is not None:
        query["operator"] = str(operator)
    for k, v in params.items():
        if v is not None:
            query[k] = str(v)
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                url, params=query,
                headers={"Accept": "application/json, text/plain, */*"},
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    return None, f"HTTP {resp.status}: {text[:160]}"
                return text, None
    except Exception as exc:
        logger.warning(f"TemporaSMS {action} failed: {exc}")
        return None, str(exc) or type(exc).__name__


async def _call_conn(session, action, operator=None, **params):
    """Same as :func:`_call` but reuses an open session (used by the sweep)."""
    url = f"{_base_url()}/stubs/handler_api.php"
    query = {"api_key": TEMPORASMS_API_KEY, "action": action}
    if operator is not None:
        query["operator"] = str(operator)
    for k, v in params.items():
        if v is not None:
            query[k] = str(v)
    async with session.get(url, params=query) as resp:
        return (await resp.text()).strip()


# --------------------------------------------------------------------------- #
#  Catalogue: which operator sells which service
# --------------------------------------------------------------------------- #
async def _catalogue():
    """Merged ``{code: {'name': str, 'operator': int}}`` across all routes.

    Service codes are operator-scoped: ``tvm`` (telegram) only exists on
    operator 13, while ``esb`` (facebook) lives on operator 1.  Merging the
    catalogues is the only way to resolve an app name to a usable
    (code, operator) pair.
    """
    now = time.time()
    if _CATALOGUE["data"] and now - _CATALOGUE["ts"] < _CATALOGUE_TTL:
        return _CATALOGUE["data"]

    async def one(op):
        text, _ = await _call("getServices", operator=op, country=0)
        data = _try_json(text)
        return op, data if isinstance(data, dict) else {}

    results = await asyncio.gather(*(one(op) for op in _OPERATORS),
                                   return_exceptions=True)
    merged = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        op, data = item
        for code, name in data.items():
            code = str(code)
            entry = merged.get(code)
            if entry is None:
                merged[code] = {"name": str(name).strip(), "operator": op,
                                "operators": [op]}
            else:
                if op not in entry["operators"]:
                    entry["operators"].append(op)
                # Prefer the operator that actually advertises the service, and
                # prefer operator 13 for the apps we care about most.
                if op == _PREFERRED_OPERATOR:
                    entry["operator"] = op
                    entry["name"] = str(name).strip()
    for entry in merged.values():
        entry["operators"].sort()
    if merged:
        _CATALOGUE["data"] = merged
        _CATALOGUE["ts"] = now
    return merged


async def resolve_service(service):
    """Map an app name/slug onto ``(provider_code, operator)``.

    Never raises; falls back to ``(slug, preferred_operator)``.
    """
    raw = str(service or "").strip()
    if not raw:
        return "", _PREFERRED_OPERATOR
    key = raw.lower()
    if key in _RESOLVED_SERVICE:
        return _RESOLVED_SERVICE[key]

    wanted = _norm_service(raw)
    catalogue = await _catalogue()
    resolved = None

    if catalogue:
        # 1. exact code
        if key in catalogue:
            e = catalogue[key]
            resolved = (key, e["operator"])
        # 2. exact name
        if resolved is None:
            for code, e in catalogue.items():
                if e["name"].strip().lower() == wanted:
                    resolved = (code, e["operator"])
                    break
        # 3. containment either way ("Telegram " / "Google, Gmail, Youtube")
        if resolved is None:
            for code, e in catalogue.items():
                nm = e["name"].strip().lower()
                if wanted and (wanted in nm or nm in wanted):
                    resolved = (code, e["operator"])
                    break
        # 4. first word of the name ("Google, Gmail, Youtube" -> google)
        if resolved is None and wanted:
            for code, e in catalogue.items():
                nm = e["name"].strip().lower()
                if nm.split(",")[0].strip() == wanted:
                    resolved = (code, e["operator"])
                    break

    if resolved is None:
        resolved = (wanted or key, _PREFERRED_OPERATOR)
    _RESOLVED_SERVICE[key] = resolved
    return resolved


async def _resolve_service(service):
    """Backwards-compatible alias returning just the provider code."""
    code, _op = await resolve_service(service)
    return code


# --------------------------------------------------------------------------- #
#  Countries
# --------------------------------------------------------------------------- #
async def _countries_for(operator):
    """Cached ``{country_id: name}`` for one operator."""
    now = time.time()
    cached = _COUNTRIES_CACHE.get(operator)
    if cached and now - cached["ts"] < _COUNTRIES_TTL and cached["data"]:
        return cached["data"]
    text, _ = await _call("getCountries", operator=operator)
    data = _try_json(text)
    rows = {}
    if isinstance(data, dict):
        for cid, name in data.items():
            if str(cid).isdigit() and isinstance(name, str):
                rows[str(cid)] = name.strip()
    if rows:
        _COUNTRIES_CACHE[operator] = {"ts": now, "data": rows}
    return rows


def _iso_for(name):
    try:
        from utils.country_search import resolve_country
        r = resolve_country(name)
        if r:
            return r.get("iso2")
    except Exception:
        pass
    return None


async def _sweep_prices(code, operator):
    """Price + stock for one service across every country of an operator.

    ``getPrices*`` has no "all countries" mode, so this fans out over the
    country list with a bounded semaphore.  ~150 requests at concurrency 20
    finishes in a couple of seconds and the result is cached for 3 minutes.
    """
    countries = await _countries_for(operator)
    if not countries:
        return {}

    sem = asyncio.Semaphore(_SWEEP_CONCURRENCY)

    async def one(session, cid):
        async with sem:
            try:
                txt = await _call_conn(session, "getPricesV3", operator=operator,
                                       service=code, country=cid)
            except Exception:
                return cid, None
        data = _try_json(txt)
        if not isinstance(data, dict):
            return cid, None
        node = data.get(str(cid)) or {}
        node = node.get(code) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return cid, None
        price = _num(node.get("price"))
        stock = int(_num(node.get("count"), 0) or 0)
        if price is None:
            return cid, None
        return cid, {"price": price, "stock": stock}

    async with aiohttp.ClientSession(timeout=_SWEEP_TIMEOUT) as session:
        results = await asyncio.gather(*(one(session, c) for c in countries),
                                       return_exceptions=True)

    out = {}
    for item in results:
        if isinstance(item, Exception) or not item:
            continue
        cid, info = item
        if info:
            out[str(cid)] = info
    return out


async def _prices_for(service):
    """Cached ``{country_id: {'price','stock'}}`` for a service."""
    key = _norm_service(service)
    now = time.time()
    cached = _PRICES_CACHE.get(key)
    if cached and now - cached["ts"] < _PRICES_TTL and cached["data"]:
        return cached["data"]

    code, operator = await resolve_service(service)
    merged = await _sweep_prices(code, operator)
    if merged:
        _PRICES_CACHE[key] = {"ts": now, "data": merged}
    return merged


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
async def get_balance():
    text, err = await _call("getBalance")
    if text is None:
        return {"ok": False, "error": err, "balance": 0.0, "currency": "RUB"}
    text = text.strip()
    if text.startswith("ACCESS_BALANCE:"):
        return {"ok": True, "balance": _num(text.split(":", 1)[1], 0.0) or 0.0,
                "currency": "RUB"}
    data = _try_json(text)
    if isinstance(data, dict):
        node = data.get("data") if isinstance(data.get("data"), dict) else data
        for k in ("balance", "amount", "wallet", "credit"):
            if k in node:
                return {"ok": True, "balance": _num(node[k], 0.0) or 0.0,
                        "currency": str(node.get("currency", "RUB")).upper()}
    return {"ok": False,
            "error": friendly_error(text) or text[:160] or "Unknown balance response",
            "balance": 0.0, "currency": "RUB"}


async def get_services():
    """Provider catalogue as ``[{'slug','name','operator'}]``."""
    catalogue = await _catalogue()
    if not catalogue:
        return {"ok": False, "error": "Could not load the service catalogue",
                "services": []}
    services = [{"slug": code, "name": e["name"], "operator": e["operator"]}
                for code, e in catalogue.items()]
    services.sort(key=lambda s: s["name"].lower())
    return {"ok": True, "services": services}


async def get_countries(service: str):
    """Countries available for a service, with live price + stock.

    Returns ``{"ok": bool, "countries": [{code, name, price, stock, id}],
    "error"}`` where ``code`` is ISO-2 (so the UI can show flags and the buy
    flow can round-trip it) and ``id`` is the provider's numeric country id.
    """
    if not configured():
        return {"ok": False, "error": "TEMPORASMS_API_KEY is not configured",
                "countries": []}

    code, operator = await resolve_service(service)
    prices = await _prices_for(service)
    if not prices:
        return {
            "ok": False,
            "error": (f"The panel returned no prices for '{service}' "
                      f"(code {code}, route {operator})."),
            "countries": [],
        }

    names = await _countries_for(operator)
    rows = []
    for cid, info in prices.items():
        name = names.get(str(cid)) or f"Country {cid}"
        iso = _iso_for(name)
        rows.append({
            "code": (iso or f"id{cid}").lower(),
            "name": name,
            "price": info.get("price"),
            "stock": int(info.get("stock") or 0),
            "id": str(cid),
        })

    # Only show countries that actually have stock or a price.
    priced = [r for r in rows if r["price"] is not None or r["stock"] > 0]
    if not priced:
        return {"ok": False,
                "error": f"No country on the panel currently sells '{service}'.",
                "countries": []}

    best = {}
    for r in priced:
        prev = best.get(r["code"])
        if prev is None or (r["price"] is not None and
                            (prev["price"] is None or r["price"] < prev["price"])):
            best[r["code"]] = r
    ordered = sorted(best.values(),
                     key=lambda c: (c["price"] is None, c["price"] or 0, c["name"]))
    return {"ok": True, "countries": ordered, "service_code": code,
            "operator": operator}


async def _resolve_country_id(country, operator=None):
    """Map any country identifier (ISO-2/ISO-3/name/numeric id) to the
    provider's numeric country id."""
    s = str(country or "").strip()
    if not s:
        return None
    if s.isdigit():
        return s
    if s.lower().startswith("id") and s[2:].isdigit():
        return s[2:]

    countries = await _countries_for(operator or _PREFERRED_OPERATOR)
    if not countries:
        countries = await _countries_for(1)
    try:
        from utils.country_search import country_matches
    except Exception:
        country_matches = None

    low = s.lower()
    # 1. exact ISO-2 / ISO-3 hit.  This must come first: a loose matcher sees
    #    "in" inside "Philippines" and would hand back the wrong country id.
    for cid, name in countries.items():
        iso = (_iso_for(name) or "").lower()
        if iso and iso == low:
            return cid
    # 2. exact country name
    for cid, name in countries.items():
        if name.strip().lower() == low:
            return cid
    # 3. fuzzy (ISO-3, dial code, alias, "uk"/"usa", ...)
    for cid, name in countries.items():
        iso = _iso_for(name)
        if country_matches and iso and country_matches(s, iso, name):
            return cid
    # 4. substring, longest name first so "United States" beats "States"
    for cid, name in sorted(countries.items(), key=lambda kv: -len(kv[1])):
        if low and low in name.lower():
            return cid
    return None


def _parse_activation(text):
    """Normalise ``getNumber`` / ``getNumberV2`` into (order_id, phone)."""
    if not text:
        return None, None
    text = text.strip()
    if text.startswith("ACCESS_NUMBER:"):
        parts = text.split(":")
        if len(parts) >= 3:
            return parts[1], parts[2]
        return None, None
    data = _try_json(text)
    if isinstance(data, dict):
        node = data
        for wrapper in ("data", "item", "activation", "result"):
            if isinstance(node.get(wrapper), dict):
                node = node[wrapper]
                break
        oid = (node.get("id") or node.get("activationId")
               or node.get("activation_id") or node.get("order_id"))
        phone = (node.get("phone") or node.get("phoneNumber")
                 or node.get("number") or node.get("msisdn"))
        if oid and phone:
            return str(oid), str(phone)
    return None, None


async def _operators_for_code(code):
    """Every operator that advertises ``code``, preferred route first.

    Country ids are per-operator, so when a country is missing from the
    preferred route we must retry on another route that carries the service
    *and* lists that country.
    """
    cat = await _catalogue()
    entry = cat.get(str(code))
    if not entry:
        return [_PREFERRED_OPERATOR]
    ops = list(entry.get("operators") or [])
    pref = entry.get("operator")
    if pref in ops:
        ops.remove(pref)
        ops.insert(0, pref)
    return ops or [pref or _PREFERRED_OPERATOR]


async def resolve_country_route(service, country):
    """Resolve a country for a service across every route that carries it.

    Returns ``(country_id, operator, service_code)``.  ``country_id`` is
    ``None`` when no route lists the country.
    """
    code, operator = await resolve_service(service)
    pid = await _resolve_country_id(country, operator)
    if pid is not None:
        return pid, operator, code
    for op in await _operators_for_code(code):
        if op == operator:
            continue
        pid = await _resolve_country_id(country, op)
        if pid is not None:
            return pid, op, code
    return None, operator, code


async def buy_number(service: str, country: str):
    """Request a number. Returns ``{ok, order_id, phone, provider, error}``."""
    if not configured():
        return {"ok": False, "error": "TEMPORASMS_API_KEY is not configured",
                "order_id": None, "phone": None}

    pid, operator, code = await resolve_country_route(service, country)
    if pid is None:
        return {"ok": False, "error": f"Unknown country '{country}' on panel",
                "order_id": None, "phone": None}

    attempts = [
        ("getNumberV2", {"service": code, "country": pid,
                         "operator": operator, "type": "best"}),
        ("getNumberV2", {"service": code, "country": pid, "type": "best"}),
        ("getNumber", {"service": code, "country": pid, "operator": operator}),
        ("getNumber", {"service": code, "country": pid}),
    ]
    last = None
    for action, params in attempts:
        text, err = await _call(action, **params)
        if text is None:
            last = err
            continue
        oid, phone = _parse_activation(text)
        if oid and phone:
            return {"ok": True, "order_id": str(oid), "phone": str(phone),
                    "provider": "temporasms", "service_code": code,
                    "operator": operator, "error": None}
        last = friendly_error(text) or text.strip()[:160]
        # A hard provider error (no balance / bad key) will not be fixed by
        # retrying a different spelling, so stop early on those.
        if _error_code(text) in ("NO_BALANCE", "BAD_KEY", "USER_BANNED"):
            break

    return {"ok": False, "error": last or "No number available",
            "order_id": None, "phone": None}


async def get_otp(order_id: str):
    """Poll for the SMS code. Returns ``{ok, otp, status, error}``."""
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
            return {"ok": True, "otp": str(otp), "status": "received",
                    "error": None}
        return {"ok": False, "otp": None, "status": status, "error": None}
    return {"ok": False, "otp": None, "status": "waiting",
            "error": friendly_error(text)}


def _cancel_was_acknowledged(text):
    """Recognise documented text replies and explicit JSON cancel success."""
    raw = str(text or "").strip()
    data = _try_json(raw)
    if isinstance(data, dict):
        node = data.get("data") if isinstance(data.get("data"), dict) else data
        for flag in ("ok", "success"):
            if flag in node:
                return node[flag] is True
        status = str(node.get("status") or node.get("result") or "").strip().lower()
        if status in {"cancelled", "canceled", "cancel", "status_cancel", "access_cancel", "success"}:
            return True
    reply_code = raw.upper().split(":", 1)[0].strip()
    return reply_code in {"ACCESS_CANCEL", "STATUS_CANCEL", "CANCELLED", "CANCELED", "SUCCESS", "OK"}


async def cancel(order_id: str):
    """Cancel an activation and confirm the provider accepted status=8."""
    text, err = await _call("setStatus", id=order_id, status="8")
    if text is None:
        return {"ok": False, "error": err or "No response from the number provider"}
    if _error_code(text):
        return {"ok": False, "error": friendly_error(text)}
    if not _cancel_was_acknowledged(text):
        return {
            "ok": False,
            "error": f"Provider did not confirm cancellation: {str(text).strip()[:160]}",
        }
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


async def check_connection():
    """Admin helper: verify the key and show the panel balance."""
    if not configured():
        return False, "TEMPORASMS_API_KEY is not configured."
    bal = await get_balance()
    if not bal.get("ok"):
        return False, f"Panel rejected the key: {bal.get('error')}"
    catalogue = await _catalogue()
    tg = await resolve_service("telegram")
    wa = await resolve_service("whatsapp")
    lines = [
        "\u2705 <b>TemporaSMS connected!</b>",
        f"\U0001F4B0 Balance: <b>{bal['balance']:.4f}</b>",
        f"\U0001F5C2 Services in catalogue: <b>{len(catalogue)}</b>",
        f"\u2708\ufe0f Telegram: <code>{tg[0]}</code> (route {tg[1]})",
        f"\U0001F4AC WhatsApp: <code>{wa[0]}</code> (route {wa[1]})",
    ]
    return True, "\n".join(lines)


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
