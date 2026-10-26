"""TemporaSMS API client.

Powers the three product panels:
    * WhatsApp Account panel
    * TG Number Change panel
    * All Apps OTP panel (service = selected app slug)

The public TemporaSMS API surface differs between reseller accounts, so this
client is deliberately tolerant: every logical call tries a small list of
plausible endpoint paths and normalises whichever JSON shape comes back. If
the API is unreachable the caller gets `{"ok": False, "error": ...}` and the
bot shows a friendly message instead of crashing.

Environment:
    TEMPORASMS_API_KEY     -> your TemporaSMS API key (required)
    TEMPORASMS_BASE_URL    -> default https://api.temporasms.com
"""
import asyncio
import json

import aiohttp

from config import (
    TEMPORASMS_API_KEY,
    TEMPORASMS_BASE_URL,
    logger,
)

_TIMEOUT = aiohttp.ClientTimeout(total=25)


def configured() -> bool:
    return bool(TEMPORASMS_API_KEY)


def _headers():
    return {
        "Authorization": f"Bearer {TEMPORASMS_API_KEY}",
        "X-API-Key": TEMPORASMS_API_KEY,
        "Accept": "application/json",
    }


async def _get_json(paths, params=None):
    """Try each path until one returns JSON. Returns (data, error)."""
    if not configured():
        return None, "TEMPORASMS_API_KEY is not configured"
    base = (TEMPORASMS_BASE_URL or "https://api.temporasms.com").rstrip("/")
    params = dict(params or {})
    params.setdefault("api_key", TEMPORASMS_API_KEY)
    last_err = "unknown error"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            for path in paths:
                url = f"{base}{path}"
                try:
                    async with session.get(url, headers=_headers(), params=params) as resp:
                        text = await resp.text()
                        if resp.status >= 400:
                            last_err = f"HTTP {resp.status}: {text[:160]}"
                            continue
                        try:
                            return json.loads(text), None
                        except json.JSONDecodeError:
                            last_err = f"Non-JSON response from {path}"
                            continue
                except Exception as exc:
                    last_err = str(exc)
                    continue
    except Exception as exc:
        last_err = str(exc)
    return None, last_err


def _as_list(data):
    """Pull a list out of whatever wrapper the API used."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "result", "items", "services", "countries",
                    "prices", "orders", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return [dict(v, id=k) if isinstance(v, dict) else v
                        for k, v in value.items()]
        return [data]
    return []


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def get_balance():
    data, err = await _get_json(["/api/balance", "/balance", "/api/v1/balance",
                                 "/api/user/balance"])
    if data is None:
        return {"ok": False, "error": err, "balance": 0.0, "currency": "INR"}
    if isinstance(data, dict):
        node = data.get("data") if isinstance(data.get("data"), dict) else data
        for key in ("balance", "amount", "wallet", "credit"):
            if key in node:
                return {"ok": True, "balance": _num(node[key]),
                        "currency": str(node.get("currency", "INR")).upper()}
    return {"ok": True, "balance": 0.0, "currency": "INR"}


async def get_services():
    data, err = await _get_json(["/api/services", "/services", "/api/v1/services",
                                 "/api/products"])
    if data is None:
        return {"ok": False, "error": err, "services": []}
    services = []
    for item in _as_list(data):
        if isinstance(item, dict):
            slug = item.get("code") or item.get("slug") or item.get("service") or item.get("id")
            name = item.get("name") or item.get("title") or slug
            if slug:
                services.append({"slug": str(slug), "name": str(name)})
        elif isinstance(item, str):
            services.append({"slug": item, "name": item})
    return {"ok": True, "services": services}


async def get_countries(service: str):
    """Countries available for a service, with live price per country."""
    data, err = await _get_json(
        [f"/api/countries/{service}", f"/api/v1/countries/{service}",
         "/api/countries", "/countries"],
        params={"service": service},
    )
    if data is None:
        return {"ok": False, "error": err, "countries": []}

    countries = []
    for item in _as_list(data):
        if not isinstance(item, dict):
            continue
        code = (item.get("code") or item.get("iso") or item.get("country")
                or item.get("id") or item.get("slug"))
        name = item.get("name") or item.get("country_name") or code
        if not code:
            continue
        price = None
        for key in ("price", "cost", "rate", "amount"):
            if key in item:
                price = _num(item[key], None)
                break
        if price is None and isinstance(item.get("prices"), dict):
            price = _num(next(iter(item["prices"].values()), 0), None)
        stock = item.get("stock", item.get("count", item.get("available", 0)))
        countries.append({
            "code": str(code).lower(),
            "name": str(name),
            "price": price,
            "stock": int(_num(stock, 0)),
        })

    # de-duplicate by code, cheapest first (users always see cheapest first)
    best = {}
    for c in countries:
        prev = best.get(c["code"])
        if prev is None or (c["price"] is not None and
                            (prev["price"] is None or c["price"] < prev["price"])):
            best[c["code"]] = c
    ordered = sorted(best.values(),
                     key=lambda c: (c["price"] is None, c["price"] or 0, c["name"]))
    return {"ok": True, "countries": ordered}


async def buy_number(service: str, country: str):
    """Request a number. Returns {ok, order_id, phone, error}."""
    data, err = await _get_json(
        ["/api/get_number", "/api/v1/get_number", "/api/number", "/get_number",
         "/api/purchase"],
        params={"service": service, "country": country},
    )
    if data is None:
        return {"ok": False, "error": err, "order_id": None, "phone": None}

    node = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(node, dict):
        return {"ok": False, "error": "Unexpected response from TemporaSMS",
                "order_id": None, "phone": None}

    order_id = node.get("order_id") or node.get("id") or node.get("order") or node.get("activation_id")
    phone = node.get("phone") or node.get("number") or node.get("msisdn")
    success = node.get("success", node.get("ok", True))
    if not success or not order_id:
        return {"ok": False,
                "error": str(node.get("message") or node.get("error") or "No number available"),
                "order_id": None, "phone": None}
    return {"ok": True, "order_id": str(order_id), "phone": str(phone or ""),
            "raw": node, "error": None}


async def get_otp(order_id: str):
    """Poll for the SMS code. Returns {ok, otp, status, error}."""
    data, err = await _get_json(
        ["/api/get_code", "/api/v1/get_code", "/api/otp", "/get_code", "/api/status"],
        params={"order_id": order_id, "id": order_id},
    )
    if data is None:
        return {"ok": False, "otp": None, "status": "error", "error": err}
    node = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(node, dict):
        return {"ok": False, "otp": None, "status": "error", "error": "Unexpected response"}
    otp = node.get("otp") or node.get("code") or node.get("sms_code") or node.get("message")
    status = str(node.get("status", "waiting")).lower()
    if otp:
        return {"ok": True, "otp": str(otp), "status": "received", "error": None}
    return {"ok": False, "otp": None, "status": status, "error": None}


async def cancel(order_id: str):
    data, err = await _get_json(
        ["/api/cancel", "/api/v1/cancel", "/api/cancel_number"],
        params={"order_id": order_id, "id": order_id},
    )
    if data is None:
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
    ("usa", "🇺🇸 USA"), ("india", "🇮🇳 India"), ("england", "🇬🇧 United Kingdom"),
    ("indonesia", "🇮🇩 Indonesia"), ("philippines", "🇵🇭 Philippines"),
    ("vietnam", "🇻🇳 Vietnam"), ("canada", "🇨🇦 Canada"), ("ukraine", "🇺🇦 Ukraine"),
    ("kazakhstan", "🇰🇿 Kazakhstan"), ("brazil", "🇧🇷 Brazil"),
    ("russia", "🇷🇺 Russia"), ("germany", "🇩🇪 Germany"),
    ("france", "🇫🇷 France"), ("spain", "🇪🇸 Spain"), ("italy", "🇮🇹 Italy"),
    ("mexico", "🇲🇽 Mexico"), ("nigeria", "🇳🇬 Nigeria"), ("kenya", "🇰🇪 Kenya"),
    ("pakistan", "🇵🇰 Pakistan"), ("bangladesh", "🇧🇩 Bangladesh"),
    ("nepal", "🇳🇵 Nepal"), ("srilanka", "🇱🇰 Sri Lanka"),
    ("uae", "🇦🇪 UAE"), ("saudiarabia", "🇸🇦 Saudi Arabia"),
    ("turkey", "🇹🇷 Turkey"), ("egypt", "🇪🇬 Egypt"),
    ("southafrica", "🇿🇦 South Africa"), ("australia", "🇦🇺 Australia"),
    ("malaysia", "🇲🇾 Malaysia"), ("thailand", "🇹🇭 Thailand"),
]


def fallback_countries():
    return [{"code": c, "name": n, "price": None, "stock": 0}
            for c, n in FALLBACK_COUNTRIES]
