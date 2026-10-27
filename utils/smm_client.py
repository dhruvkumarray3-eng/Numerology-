import aiohttp
import asyncio
import logging
import os
import time
from config import logger
from database import to_usd


def _env(name, default=""):
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


# ---------------------------------------------------------------------------
# SMM providers
#
# Primary provider is fathersmm.com.  Both the API URL and the API key are
# read from environment variables so the owner can rotate them without
# touching the code:
#
#     FATHERSMM_API_URL   (default: https://fathersmm.com/api/v2)
#     FATHERSMM_API_KEY   (required for live data)
#     FATHERSMM_CURRENCY  (default: INR)
#
# A secondary provider is kept as a fallback and is likewise env-driven.
# ---------------------------------------------------------------------------
FATHERSMM_API_URL = _env("FATHERSMM_API_URL", "https://fathersmm.com/api/v2")
FATHERSMM_API_KEY = _env("FATHERSMM_API_KEY", "7693898241322ddfeea23dca2e59fc88")
FATHERSMM_CURRENCY = _env("FATHERSMM_CURRENCY", "INR").upper()

SMM_SERVER2_URL = _env("SMM_SERVER2_API_URL", "https://best-smm.com/api/v2")
SMM_SERVER2_KEY = _env("SMM_SERVER2_API_KEY", "cc77a5fe7218f0bc0c38e2a7f768c77f")
SMM_SERVER2_CURRENCY = _env("SMM_SERVER2_CURRENCY", "USD").upper()

SMM_SERVERS = {
    1: {
        'name': '\U0001d5e9\U0001d5dc\U0001d5df \U0001d5e6\U0001d5f2\U0001d5ff\U0001d5ff\U0001d5f2\U0001d5ff 1 (\U0001d5d5\U0001d5ee\U0001d5fc\U0001d601 & \U0001d5dc\U0001d5fb\U0001d600\U0001d601\U0001d5ee\U0001d5fb\U0001d601)',
        'url': FATHERSMM_API_URL,
        'key': FATHERSMM_API_KEY,
        'currency': FATHERSMM_CURRENCY
    },
    2: {
        'name': '\U0001d5d5\U0001d602\U0001d5f1\U0001d5f4\U0001d5f2\U0001d601 \U0001d5e6\U0001d5f2\U0001d5ff\U0001d5ff\U0001d5f2\U0001d5ff 2 (\U0001d5d6\U0001d5f1\U0001d5f2\U0001d5ee\U0001d5f9\U0001d5f2\U0001d600\U0001d601 \U0001d5e5\U0001d5ee\U0001d601\U0001d5f2)',
        'url': SMM_SERVER2_URL,
        'key': SMM_SERVER2_KEY,
        'currency': SMM_SERVER2_CURRENCY
    }
}

# ---------------------------------------------------------------------------
# Server ON/OFF switches (owner-controlled)
#
# The owner wants to run only FathersMM (server 1) while keeping server 2 in
# the code but switched OFF for normal users.  Each server has a persisted
# switch in the ``settings`` table so the owner can flip it at will from the
# admin panel or with /smmserver.  Server 1 defaults to ON, server 2 to OFF.
# ---------------------------------------------------------------------------
SMM_SERVER_SETTING_KEYS = {1: "smm_server_1_enabled", 2: "smm_server_2_enabled"}
SMM_SERVER_DEFAULT = {1: True, 2: False}
_TRUTHY = ("1", "on", "true", "yes", "enabled", "active")


def _read_setting(key, default=None):
    try:
        from database import cur
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row and row[0] not in (None, ""):
            return row[0]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"smm setting read failed for {key}: {exc}")
    return default


def _write_setting(key, value):
    try:
        from database import cur, db
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        db.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"smm setting write failed for {key}: {exc}")
        return False


def is_server_enabled(server):
    """Return True when the given SMM server is switched ON by the owner."""
    try:
        server = int(server)
    except (TypeError, ValueError):
        return False
    key = SMM_SERVER_SETTING_KEYS.get(server)
    if not key:
        return False
    default = SMM_SERVER_DEFAULT.get(server, False)
    raw = _read_setting(key, "1" if default else "0")
    return str(raw).strip().lower() in _TRUTHY


def set_server_enabled(server, enabled):
    """Persist the ON/OFF state of a server.  Returns True on success."""
    try:
        server = int(server)
    except (TypeError, ValueError):
        return False
    key = SMM_SERVER_SETTING_KEYS.get(server)
    if not key:
        return False
    return _write_setting(key, "1" if enabled else "0")


def toggle_server(server):
    """Flip a server's state and return the new boolean state."""
    new_state = not is_server_enabled(server)
    set_server_enabled(server, new_state)
    return new_state


def enabled_servers():
    """Return the list of server ids that are currently ON."""
    return [sid for sid in SMM_SERVERS if is_server_enabled(sid)]


def server_status():
    """Return {server_id: bool} for every configured server."""
    return {sid: is_server_enabled(sid) for sid in SMM_SERVERS}


_services_cache = {1: None, 2: None}
_cache_time = {1: 0, 2: 0}

PLATFORM_KEYWORDS = {
    'Telegram': ['telegram', 'tg '],
    'Instagram': ['instagram', 'ig '],
    'WhatsApp': ['whatsapp', 'wa '],
    'YouTube': ['youtube', 'yt '],
    'Facebook': ['facebook', 'fb '],
    'TikTok': ['tiktok', 'tik tok'],
    'Twitter/X': ['twitter', 'x -', 'x /']
}

PLATFORM_ICONS = {
    'Telegram': '✈️',
    'Instagram': '📸',
    'WhatsApp': '💬',
    'YouTube': '▶️',
    'Facebook': '📘',
    'TikTok': '🎵',
    'Twitter/X': '🐦',
    'Other Services': '🌐'
}

PLATFORM_PREMIUM_ICONS = {
    'Telegram': 5408995930416362034,
    'Instagram': 5409271925014801629,
    'WhatsApp': 5440627033111557670,
    'YouTube': 5409320020058584473,
    'Facebook': 6154249597532248059,
    'TikTok': 6203982793379154737,
    'Twitter/X': 6129732880529628243,
    'Other Services': 6129399728506412489
}

async def fetch_smm_services(server=1, force_refresh=False):
    global _services_cache, _cache_time
    # A server the owner has switched OFF must never serve data to users.
    if not is_server_enabled(server):
        return []
    now = time.time()
    if not force_refresh and _services_cache.get(server) and (now - _cache_time.get(server, 0) < 600):
        return _services_cache[server]
        
    srv = SMM_SERVERS.get(server, SMM_SERVERS[1])
    params = {
        'key': srv['key'],
        'action': 'services'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(srv['url'], data=params, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, list):
                        _services_cache[server] = data
                        _cache_time[server] = now
                        return data
                    else:
                        logger.error(f"SMM services returned non-list: {data}")
    except Exception as ex:
        logger.error(f"SMM fetch_services error (server {server}): {ex}")
        
    return _services_cache.get(server) or []

def detect_platform(category_name):
    c_lower = (category_name or '').lower()
    for plat, keywords in PLATFORM_KEYWORDS.items():
        for kw in keywords:
            if kw in c_lower:
                return plat
    return 'Other Services'

async def get_smm_platforms(server=1):
    services = await fetch_smm_services(server)
    found_platforms = set()
    for s in services:
        cat = s.get('category', '')
        plat = detect_platform(cat)
        found_platforms.add(plat)
    
    # Return in clean sorted order with popular first
    order = ['Telegram', 'Instagram', 'WhatsApp', 'YouTube', 'Facebook', 'TikTok', 'Twitter/X', 'Other Services']
    return [p for p in order if p in found_platforms]

async def get_categories_for_platform(platform, server=1):
    services = await fetch_smm_services(server)
    # One pass to count services per category, then one pass to build the
    # ordered list.  The old code re-scanned the whole catalogue for every
    # category (O(n^2)) which took seconds on the 2000+ service servers.
    counts = {}
    order = []
    for s in services:
        cat = s.get('category', '').strip()
        if not cat:
            continue
        if cat not in counts:
            counts[cat] = 0
            order.append(cat)
        counts[cat] += 1

    cats = []
    for cat in order:
        if detect_platform(cat) == platform:
            cats.append({'name': cat, 'count': counts[cat]})
    return cats

async def get_services_for_category(category_name, server=1):
    services = await fetch_smm_services(server)
    return [s for s in services if s.get('category', '').strip() == category_name.strip()]

async def get_smm_service_details(service_id, server=1):
    services = await fetch_smm_services(server)
    for s in services:
        if str(s.get('service')) == str(service_id):
            return s
    return None

def get_service_panel_rate(service, server=1):
    """Raw provider (panel) rate per 1000, converted to INR. No owner markup."""
    rate_raw = float(service.get('rate', 0) or 0)
    srv = SMM_SERVERS.get(server, SMM_SERVERS[1])
    if srv['currency'] == 'USD':
        # USD to INR conversion (e.g. rate in USD * 90)
        from database import get_usdt_rate
        usd_inr = get_usdt_rate() or 90.0
        return round(rate_raw * usd_inr, 2)
    return round(rate_raw, 2)


def get_service_profit_per_1k(service, server=1):
    """Owner profit added on top of the panel rate, per 1000 units."""
    try:
        from utils.markup import get_markup_config, profit_in_inr
        cfg = get_markup_config()
        panel = get_service_panel_rate(service, server)
        return round(float(profit_in_inr(panel, cfg) or 0), 2)
    except Exception:
        return 0.0


def get_service_inr_rate(service, server=1):
    """Final user-facing rate per 1000 = panel rate + owner profit.

    This is what the buyer sees and what is charged, so the owner's markup
    configured via /setprofit or /setmarkup is always included.
    """
    panel = get_service_panel_rate(service, server)
    try:
        from utils.markup import apply_markup, get_markup_config
        final = float(apply_markup(panel, get_markup_config(), minimum=0.0))
        return round(final, 2)
    except Exception:
        return panel


def get_service_breakdown(service, server=1):
    """Return (panel_rate, profit, user_rate) per 1000 for display."""
    panel = get_service_panel_rate(service, server)
    user = get_service_inr_rate(service, server)
    return panel, round(max(0.0, user - panel), 2), user

async def create_smm_order(service_id, link, quantity, server=1):
    # Never place a paid order against a server the owner has switched OFF.
    if not is_server_enabled(server):
        return {'error': 'This SMM server is currently OFF. Please try another server.'}
    srv = SMM_SERVERS.get(server, SMM_SERVERS[1])
    params = {
        'key': srv['key'],
        'action': 'add',
        'service': str(service_id),
        'link': str(link).strip(),
        'quantity': str(quantity).strip()
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(srv['url'], data=params, timeout=20) as resp:
                data = await resp.json(content_type=None)
                if isinstance(data, dict):
                    return data
                if isinstance(data, list) and data:
                    return data[0] if isinstance(data[0], dict) else {'error': str(data)}
                return {'error': 'Unexpected response from SMM server'}
    except Exception as ex:
        logger.error(f"SMM create_order error: {ex}")
        return {'error': str(ex)}

async def get_smm_order_status(order_id, server=1):
    srv = SMM_SERVERS.get(server, SMM_SERVERS[1])
    params = {
        'key': srv['key'],
        'action': 'status',
        'order': str(order_id).strip()
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(srv['url'], data=params, timeout=15) as resp:
                data = await resp.json(content_type=None)
                if isinstance(data, dict):
                    return data
                return {'error': 'Unexpected response from SMM server'}
    except Exception as ex:
        logger.error(f"SMM get_order_status error: {ex}")
        return {'error': str(ex)}
