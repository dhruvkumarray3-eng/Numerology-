"""OTP / SMS provider abstraction for the "All Apps Accounts" feature.

Supports TemporaSMS (the same panel that powers the WhatsApp / TG-number-change
flows), plus 5SIM, SMS-Activate, SMSPVA and SMS-Man as optional extras.  A
provider is only used when its API key is configured.

Important: the previous version of this module *only* ever talked to 5SIM, so a
bot configured with just ``TEMPORASMS_API_KEY`` (the normal setup) reported
"no provider configured" and zero stock for every app.  TemporaSMS is now a
first-class provider, so All Apps OTP uses the same live panel as the rest of
the bot.

All functions are defensive: on any failure they return a structured error
instead of raising, and every network call is bounded by a hard timeout so a
slow provider can never hang a Telegram handler.
"""
import asyncio
import logging

import aiohttp

from config import (
    FIVESIM_API_KEY,
    SMSACTIVATE_API_KEY,
    SMSPVA_API_KEY,
    SMSMAN_API_KEY,
    logger,
)
from utils import temporasms

# App slug -> provider service codes (best-effort defaults)
APP_SERVICE_MAP = {
    "telegram": {"5sim": "telegram", "smsactivate": "tg", "smspva": "opt16", "smsman": "tg", "temporasms": "telegram"},
    "whatsapp": {"5sim": "whatsapp", "smsactivate": "wa", "smspva": "opt14", "smsman": "wa", "temporasms": "whatsapp"},
    "instagram": {"5sim": "instagram", "smsactivate": "ig", "smspva": "opt3", "smsman": "ig", "temporasms": "instagram"},
    "facebook": {"5sim": "facebook", "smsactivate": "fb", "smspva": "opt2", "smsman": "fb", "temporasms": "facebook"},
    "twitter": {"5sim": "twitter", "smsactivate": "tw", "smspva": "opt1", "smsman": "tw", "temporasms": "twitter"},
    "tiktok": {"5sim": "tiktok", "smsactivate": "tt", "smspva": "opt47", "smsman": "tt", "temporasms": "tiktok"},
    "google": {"5sim": "google", "smsactivate": "go", "smspva": "opt4", "smsman": "go", "temporasms": "google"},
    "discord": {"5sim": "discord", "smsactivate": "ds", "smspva": "opt44", "smsman": "ds", "temporasms": "discord"},
    "uber": {"5sim": "uber", "smsactivate": "ub", "smspva": "opt12", "smsman": "ub", "temporasms": "uber"},
    "amazon": {"5sim": "amazon", "smsactivate": "am", "smspva": "opt5", "smsman": "am", "temporasms": "amazon"},
    "netflix": {"5sim": "netflix", "smsactivate": "nf", "smspva": "opt33", "smsman": "nf", "temporasms": "netflix"},
    "paypal": {"5sim": "paypal", "smsactivate": "pp", "smspva": "opt21", "smsman": "pp", "temporasms": "paypal"},
}

APP_CATALOG = [
    ("telegram", "\u2708\ufe0f Telegram"),
    ("whatsapp", "\ud83d\udcac WhatsApp"),
    ("instagram", "\ud83d\udcf8 Instagram"),
    ("facebook", "\ud83d\udcd8 Facebook"),
    ("twitter", "\ud83d\udc26 Twitter / X"),
    ("tiktok", "\ud83c\udfb5 TikTok"),
    ("google", "\ud83d\udd0d Google"),
    ("discord", "\ud83c\udfae Discord"),
    ("uber", "\ud83d\ude97 Uber"),
    ("amazon", "\ud83d\uded2 Amazon"),
    ("netflix", "\ud83c\udfac Netflix"),
    ("paypal", "\ud83d\udcb3 PayPal"),
]

# Hard ceiling for any single provider round-trip.  Telegram handlers must
# always answer quickly, so we never wait longer than this.
_CALL_TIMEOUT = 20


def available_providers():
    providers = []
    if temporasms.configured():
        providers.append("temporasms")
    if FIVESIM_API_KEY:
        providers.append("5sim")
    if SMSACTIVATE_API_KEY:
        providers.append("smsactivate")
    if SMSPVA_API_KEY:
        providers.append("smspva")
    if SMSMAN_API_KEY:
        providers.append("smsman")
    return providers


def provider_configured():
    return bool(available_providers())


def _service(app_slug, provider):
    return APP_SERVICE_MAP.get(app_slug, {}).get(provider, app_slug)


async def _tempora_countries(service):
    """Live TemporaSMS country list for a service, bounded by a timeout."""
    try:
        return await asyncio.wait_for(temporasms.get_countries(service),
                                      timeout=_CALL_TIMEOUT)
    except Exception as ex:
        logger.warning(f"TemporaSMS country lookup failed for {service}: {ex}")
        return {"ok": False, "countries": [], "error": str(ex)}


def _match_country(countries, country_iso):
    """Find the provider row that corresponds to ``country_iso``."""
    if not country_iso or country_iso in ("any", ""):
        return None
    try:
        from utils.country_search import country_matches
    except Exception:
        country_matches = None
    for c in countries or []:
        if country_matches and country_matches(
            country_iso, c.get("code"), c.get("name")
        ):
            return c
        code = str(c.get("code") or "").lower()
        if code == str(country_iso).lower():
            return c
    return None


async def _fivesim_price(service, country):
    url = f"https://5sim.net/v1/guest/prices?product={service}&country={country}"
    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers, timeout=_CALL_TIMEOUT) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            try:
                products = data[service][country]
                for _op, info in products.items():
                    if info.get("count", 0) > 0:
                        return float(info.get("cost", 0))
            except Exception:
                return None
    return None


async def get_price(app_slug, country_iso="any"):
    """Returns (price, currency, provider) or (None, None, None)."""
    # TemporaSMS is the primary panel for this bot.
    if temporasms.configured():
        service = _service(app_slug, "temporasms")
        result = await _tempora_countries(service)
        if result.get("ok"):
            match = _match_country(result.get("countries"), country_iso)
            if match and match.get("price") is not None:
                return float(match["price"]), "INR", "temporasms"
            if not country_iso or country_iso == "any":
                prices = [c["price"] for c in result.get("countries") or []
                          if c.get("price") is not None]
                if prices:
                    return float(min(prices)), "INR", "temporasms"

    if FIVESIM_API_KEY:
        service = _service(app_slug, "5sim")
        try:
            price = await asyncio.wait_for(
                _fivesim_price(service, country_iso if country_iso != "any" else "russia"),
                timeout=_CALL_TIMEOUT,
            )
            if price:
                return price, "RUB", "5sim"
        except Exception as ex:
            logger.warning(f"OTP price lookup failed for 5sim: {ex}")
    return None, None, None


async def get_stock(app_slug, country_iso="any"):
    """Live stock count for an app/country. Returns (count, price, provider).

    ``count`` is the number of activations the provider has in stock right now
    (0 when unknown).  Used by the pre-purchase stock-details card.
    """
    # --- TemporaSMS (primary) -------------------------------------------------
    if temporasms.configured():
        service = _service(app_slug, "temporasms")
        result = await _tempora_countries(service)
        if result.get("ok"):
            countries = result.get("countries") or []
            if not country_iso or country_iso == "any":
                total = sum(int(c.get("stock") or 0) for c in countries)
                prices = [c["price"] for c in countries if c.get("price") is not None]
                return total, (min(prices) if prices else None), "temporasms"
            match = _match_country(countries, country_iso)
            if match:
                return (int(match.get("stock") or 0),
                        match.get("price"), "temporasms")
            # Provider answered but has no row for this country.
            return 0, None, "temporasms"

    # --- 5SIM (optional fallback) --------------------------------------------
    service = _service(app_slug, "5sim")
    country = country_iso if country_iso not in (None, "", "any") else "russia"
    if not FIVESIM_API_KEY:
        return 0, None, None
    url = f"https://5sim.net/v1/guest/prices?product={service}&country={country}"
    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, timeout=_CALL_TIMEOUT) as r:
                if r.status != 200:
                    return 0, None, "5sim"
                data = await r.json(content_type=None)
                products = data[service][country]
                total = 0
                cheapest = None
                for _op, info in products.items():
                    count = int(info.get("count", 0) or 0)
                    cost = float(info.get("cost", 0) or 0)
                    total += count
                    if count > 0 and (cheapest is None or cost < cheapest):
                        cheapest = cost
                return total, cheapest, "5sim"
    except Exception as ex:
        logger.warning(f"OTP stock lookup failed: {ex}")
        return 0, None, None


async def buy_number(app_slug, country_iso="any"):
    """Buys a number. Returns dict {ok, phone, order_id, provider, error}."""
    # --- TemporaSMS (primary) -------------------------------------------------
    if temporasms.configured():
        service = _service(app_slug, "temporasms")
        country = country_iso if country_iso not in (None, "", "any") else "any"
        try:
            result = await asyncio.wait_for(
                temporasms.buy_number(service, country), timeout=_CALL_TIMEOUT
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "phone": result.get("phone"),
                    "order_id": result.get("order_id"),
                    "provider": "temporasms",
                }
            # Fall through to 5SIM only when it is configured, otherwise report
            # the real provider error.
            if not FIVESIM_API_KEY:
                return {"ok": False, "error": result.get("error") or "No number available"}
        except Exception as ex:
            if not FIVESIM_API_KEY:
                return {"ok": False, "error": str(ex)}

    # --- 5SIM (optional fallback) --------------------------------------------
    service = _service(app_slug, "5sim")
    if not FIVESIM_API_KEY:
        return {"ok": False, "error": "No OTP provider configured. Set TEMPORASMS_API_KEY (or FIVESIM_API_KEY) in your host variables."}
    url = f"https://5sim.net/v1/user/buy/activation/{country_iso if country_iso != 'any' else 'russia'}/any/{service}"
    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, timeout=_CALL_TIMEOUT) as r:
                data = await r.json(content_type=None)
                if r.status == 200 and data.get("id"):
                    return {
                        "ok": True,
                        "phone": data.get("phone"),
                        "order_id": data.get("id"),
                        "provider": "5sim",
                    }
                return {"ok": False, "error": str(data)[:200]}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


async def get_otp(provider, order_id):
    """Polls for an OTP code. Returns code string or None."""
    if provider == "temporasms":
        try:
            result = await asyncio.wait_for(
                temporasms.get_otp(order_id), timeout=_CALL_TIMEOUT
            )
            if result.get("otp"):
                return str(result["otp"])
        except Exception as ex:
            logger.warning(f"TemporaSMS OTP poll failed: {ex}")
        return None

    if provider == "5sim" and FIVESIM_API_KEY:
        url = f"https://5sim.net/v1/user/check/{order_id}"
        headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers, timeout=_CALL_TIMEOUT) as r:
                    if r.status != 200:
                        return None
                    data = await r.json(content_type=None)
                    sms = data.get("sms") or []
                    if sms:
                        return sms[-1].get("code")
        except Exception as ex:
            logger.warning(f"OTP poll failed: {ex}")
    return None
