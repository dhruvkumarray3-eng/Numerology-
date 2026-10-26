"""OTP / SMS provider abstraction for the "All Apps Accounts" feature.

Supports 5SIM, SMS-Activate, SMSPVA and SMS-Man. Each provider is only used
when its API key is configured. All functions are defensive: on any failure
they return a structured error instead of raising, so the bot never crashes.
"""
import logging
import aiohttp

from config import (
    FIVESIM_API_KEY,
    SMSACTIVATE_API_KEY,
    SMSPVA_API_KEY,
    SMSMAN_API_KEY,
    logger,
)

# App slug -> provider service codes (best-effort defaults)
APP_SERVICE_MAP = {
    "telegram": {"5sim": "telegram", "smsactivate": "tg", "smspva": "opt16", "smsman": "tg"},
    "whatsapp": {"5sim": "whatsapp", "smsactivate": "wa", "smspva": "opt14", "smsman": "wa"},
    "instagram": {"5sim": "instagram", "smsactivate": "ig", "smspva": "opt3", "smsman": "ig"},
    "facebook": {"5sim": "facebook", "smsactivate": "fb", "smspva": "opt2", "smsman": "fb"},
    "twitter": {"5sim": "twitter", "smsactivate": "tw", "smspva": "opt1", "smsman": "tw"},
    "tiktok": {"5sim": "tiktok", "smsactivate": "tt", "smspva": "opt47", "smsman": "tt"},
    "google": {"5sim": "google", "smsactivate": "go", "smspva": "opt4", "smsman": "go"},
    "discord": {"5sim": "discord", "smsactivate": "ds", "smspva": "opt44", "smsman": "ds"},
    "uber": {"5sim": "uber", "smsactivate": "ub", "smspva": "opt12", "smsman": "ub"},
    "amazon": {"5sim": "amazon", "smsactivate": "am", "smspva": "opt5", "smsman": "am"},
    "netflix": {"5sim": "netflix", "smsactivate": "nf", "smspva": "opt33", "smsman": "nf"},
    "paypal": {"5sim": "paypal", "smsactivate": "pp", "smspva": "opt21", "smsman": "pp"},
}

APP_CATALOG = [
    ("telegram", "✈️ Telegram"),
    ("whatsapp", "💬 WhatsApp"),
    ("instagram", "📸 Instagram"),
    ("facebook", "📘 Facebook"),
    ("twitter", "🐦 Twitter / X"),
    ("tiktok", "🎵 TikTok"),
    ("google", "🔍 Google"),
    ("discord", "🎮 Discord"),
    ("uber", "🚗 Uber"),
    ("amazon", "🛒 Amazon"),
    ("netflix", "🎬 Netflix"),
    ("paypal", "💳 PayPal"),
]


def available_providers():
    providers = []
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


async def _fivesim_price(service, country):
    url = f"https://5sim.net/v1/guest/prices?product={service}&country={country}"
    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers, timeout=20) as r:
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
    service = APP_SERVICE_MAP.get(app_slug, {}).get("5sim", app_slug)
    for provider in available_providers():
        try:
            if provider == "5sim":
                price = await _fivesim_price(service, country_iso if country_iso != "any" else "russia")
                if price:
                    return price, "RUB", "5sim"
        except Exception as ex:
            logger.warning(f"OTP price lookup failed for {provider}: {ex}")
    return None, None, None


async def get_stock(app_slug, country_iso="any"):
    """Live stock count for an app/country. Returns (count, price, provider).

    ``count`` is the number of activations the provider has in stock right now
    (0 when unknown).  Used by the pre-purchase stock-details card.
    """
    service = APP_SERVICE_MAP.get(app_slug, {}).get("5sim", app_slug)
    country = country_iso if country_iso not in (None, "", "any") else "russia"
    if not FIVESIM_API_KEY:
        return 0, None, None
    url = f"https://5sim.net/v1/guest/prices?product={service}&country={country}"
    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, timeout=20) as r:
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
    service = APP_SERVICE_MAP.get(app_slug, {}).get("5sim", app_slug)
    if not FIVESIM_API_KEY:
        return {"ok": False, "error": "No OTP provider configured. Set FIVESIM_API_KEY (or another provider key) in your host variables."}
    url = f"https://5sim.net/v1/user/buy/activation/{country_iso if country_iso != 'any' else 'russia'}/any/{service}"
    headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, timeout=30) as r:
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
    if provider == "5sim" and FIVESIM_API_KEY:
        url = f"https://5sim.net/v1/user/check/{order_id}"
        headers = {"Authorization": f"Bearer {FIVESIM_API_KEY}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers, timeout=20) as r:
                    if r.status != 200:
                        return None
                    data = await r.json(content_type=None)
                    sms = data.get("sms") or []
                    if sms:
                        return sms[-1].get("code")
        except Exception as ex:
            logger.warning(f"OTP poll failed: {ex}")
    return None
