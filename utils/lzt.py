import os
import time
import datetime
import aiohttp
import asyncio
import json
import logging
from html import escape as html_escape
from config import logger
from database import cur, db, get_flag_by_country_name

# Admin-tunable live-search behaviour (sort order, filters, price window,
# page/result limits, strict spam verification).  Imported defensively so the
# module still works if the settings table/module is unavailable.
try:
    from utils.search_settings import (
        resolve_order,
        resolve_mode,
        price_bounds,
        int_setting,
        is_strict_spam,
        allow_geo_spam,
        auto_fallback,
    )
except Exception:  # pragma: no cover - defensive fallback
    def resolve_order(mode, *a, **k):
        return "price_to_up"

    def resolve_mode(mode, *a, **k):
        return mode

    def price_bounds(*a, **k):
        return None, None

    def int_setting(key, fallback):
        try:
            return int(fallback)
        except Exception:
            return fallback

    def is_strict_spam(*a, **k):
        return False

    def allow_geo_spam(*a, **k):
        return True

    def auto_fallback(*a, **k):
        return True

LZT_BASE_URL = "https://api.lzt.market"

# Category Search allows 20 requests/minute -> keep a global 3s gap.
_LZT_SEARCH_LOCK = asyncio.Lock()
_LZT_LAST_CALL = 0.0
_LZT_MIN_INTERVAL = 3.0

# LZT's own docs say: "It's highly recommended to set the request timeout to
# 300+ seconds, because certain methods can take a long time to be processed."
# The old 20s timeout was aborting perfectly valid category searches, which the
# UI then rendered as "No live accounts found".
_LZT_REQUEST_TIMEOUT = 75

def validate_token_format(token):
    """Check that ``token`` looks like an LZT *Access Token*, not a Client ID.

    lolz.live shows three different strings on the API pages and it is very
    easy to copy the wrong one:

      * **Client ID**      - short number, e.g. ``1234``
      * **Client Secret**  - long random hex/alnum string
      * **Access Token**   - a JWT: three dot-separated parts, always starting
        with ``eyJ`` (base64 of ``{"`` )

    Only the Access Token works with ``Authorization: Bearer ...``.

    Returns ``(ok, reason)`` where ``reason`` explains what was pasted.
    """
    t = str(token or "").strip()
    if not t:
        return False, "empty"

    # Strip an accidental "Bearer " prefix the user may have copied.
    if t.lower().startswith("bearer "):
        t = t[7:].strip()

    parts = t.split(".")
    if len(parts) == 3 and t.startswith("eyJ") and all(parts):
        return True, "jwt"

    if t.isdigit():
        return False, (
            "This looks like a **Client ID** (a short number). That is not the "
            "token - it will always be rejected."
        )

    if len(parts) == 3:
        return False, (
            "This looks like a JWT but not an LZT one (it does not start with "
            "`eyJ`). Make sure you copied the **Access Token** and not a token "
            "from another service."
        )

    if len(t) >= 20 and "." not in t:
        return False, (
            "This looks like a **Client Secret** (one long string, no dots). "
            "The bot needs the **Access Token**, which is a long string with "
            "two dots in it."
        )

    return False, (
        "This does not look like an LZT Access Token. A real token is a long "
        "string with two dots (like `eyJhbGciOi....eyJzdWIi....signature`)."
    )


def token_fingerprint(token):
    """Short, non-reversible-ish fingerprint so admins can tell tokens apart."""
    t = str(token or "").strip()
    if not t:
        return "not set"
    if len(t) <= 14:
        return f"len={len(t)}"
    return f"{t[:8]}…{t[-6:]} (len={len(t)})"


def classify_lzt_error(status, body):
    """Turn an LZT HTTP error into ``(kind, human_message)``.

    This matters a lot: LZT returns **403 for two completely different
    problems** --

      * the token is bad / lacks the ``market`` scope, and
      * the account is not allowed to use the Market API at all
        ("To use the Market API, you need to have 200 sympathies, or you can
        purchase a monthly subscription").

    The old code reported both as "API key invalid", so a perfectly good key
    on an account without market access looked like a broken key (and the
    search looked like an empty market).  We now read the body to tell them
    apart.
    """
    body = str(body or "")
    low = body.lower()

    if status == 401:
        return "auth", (
            "LZT rejected the API key (HTTP 401). The token is invalid, "
            "expired or revoked. Regenerate it at lolz.live > Account > API > "
            "Get Access Token and set it in Admin > LZT Panel Settings."
        )

    if status in (402, 403):
        access_markers = (
            "sympath", "subscription", "upgrade", "not have access",
            "access to the market", "buy access", "payment",
        )
        if status == 402 or any(m in low for m in access_markers):
            return "access", (
                "LZT Market API access is not enabled for this account "
                f"(HTTP {status}). LZT requires 200 sympathies or an active "
                "paid monthly subscription to use Market search."
            )
        return "auth", (
            f"LZT says HTTP {status} Forbidden. The token is valid but lacks "
            "the 'market' scope. Regenerate it with the market scope enabled."
        )

    if status == 429:
        return "rate", (
            "LZT rate limit hit (429). Category search allows 20 requests per "
            "minute with a 3s gap. Try again in a minute or lower Max Pages."
        )

    if status == 400:
        return "bad", f"LZT rejected the search parameters (HTTP 400): {body[:200]}"

    if status and 500 <= int(status) < 600:
        return "server", (
            f"LZT is having server trouble (HTTP {status}). Please retry in a "
            "few seconds."
        )

    return "unknown", f"LZT /telegram returned {status}: {body[:180]}"


# Comprehensive Country Name to ISO 3166-1 alpha-2 mapping with all aliases
COUNTRY_TO_LZT = {
    'USA/Canada': 'us', 'USA': 'us', 'United States': 'us', 'United States of America': 'us',
    'Russia': 'ru', 'Russian Federation': 'ru',
    'UK': 'gb', 'United Kingdom': 'gb', 'Great Britain': 'gb', 'Britain': 'gb', 'England': 'gb',
    'India': 'in', 'Indonesia': 'id', 'Brazil': 'br', 'Brasil': 'br',
    'Pakistan': 'pk', 'Bangladesh': 'bd', 'Nigeria': 'ng', 'Philippines': 'ph',
    'Egypt': 'eg', 'Vietnam': 'vn', 'Viet Nam': 'vn', 'Turkey': 'tr', 'Turkiye': 'tr',
    'Iran': 'ir', 'Thailand': 'th', 'Germany': 'de', 'France': 'fr', 'Italy': 'it',
    'South Africa': 'za', 'Myanmar': 'mm', 'Burma': 'mm', 'South Korea': 'kr', 'Korea': 'kr',
    'Colombia': 'co', 'Spain': 'es', 'Argentina': 'ar', 'Algeria': 'dz', 'Ukraine': 'ua',
    'Iraq': 'iq', 'Afghanistan': 'af', 'Poland': 'pl', 'Canada': 'ca', 'Morocco': 'ma',
    'Saudi Arabia': 'sa', 'Uzbekistan': 'uz', 'Peru': 'pe', 'Angola': 'ao', 'Malaysia': 'my',
    'Mozambique': 'mz', 'Ghana': 'gh', 'Yemen': 'ye', 'Nepal': 'np', 'Venezuela': 've',
    'Madagascar': 'mg', 'Cameroon': 'cm', 'Ivory Coast': 'ci', 'North Korea': 'kp',
    'Australia': 'au', 'Taiwan': 'tw', 'Sri Lanka': 'lk', 'Kazakhstan': 'kz', 'Chile': 'cl',
    'Zambia': 'zm', 'Romania': 'ro', 'Chad': 'td', 'Somalia': 'so', 'Senegal': 'sn',
    'Netherlands': 'nl', 'Ecuador': 'ec', 'Guatemala': 'gt', 'Zimbabwe': 'zw',
    'Cambodia': 'kh', 'Rwanda': 'rw', 'Benin': 'bj', 'Burundi': 'bi', 'Tunisia': 'tn',
    'Bolivia': 'bo', 'Belgium': 'be', 'Haiti': 'ht', 'Cuba': 'cu', 'South Sudan': 'ss',
    'Dominican Republic': 'do', 'Czech Republic': 'cz', 'Czechia': 'cz', 'Greece': 'gr',
    'Jordan': 'jo', 'Portugal': 'pt', 'Azerbaijan': 'az', 'Sweden': 'se', 'Honduras': 'hn',
    'UAE': 'ae', 'United Arab Emirates': 'ae', 'Hungary': 'hu', 'Tajikistan': 'tj',
    'Belarus': 'by', 'Austria': 'at', 'Papua New Guinea': 'pg', 'Serbia': 'rs',
    'Israel': 'il', 'Switzerland': 'ch', 'Togo': 'tg', 'Sierra Leone': 'sl', 'Hong Kong': 'hk',
    'Laos': 'la', 'Paraguay': 'py', 'Bulgaria': 'bg', 'Libya': 'ly', 'Lebanon': 'lb',
    'Nicaragua': 'ni', 'Kyrgyzstan': 'kg', 'El Salvador': 'sv', 'Turkmenistan': 'tm',
    'Singapore': 'sg', 'Denmark': 'dk', 'Finland': 'fi', 'Congo': 'cg', 'Slovakia': 'sk',
    'Norway': 'no', 'Oman': 'om', 'Costa Rica': 'cr', 'Liberia': 'lr', 'Ireland': 'ie',
    'New Zealand': 'nz', 'Kuwait': 'kw', 'Panama': 'pa', 'Croatia': 'hr', 'Georgia': 'ge',
    'Eritrea': 'er', 'Uruguay': 'uy', 'Bosnia and Herzegovina': 'ba', 'Mongolia': 'mn',
    'Armenia': 'am', 'Jamaica': 'jm', 'Qatar': 'qa', 'Albania': 'al', 'Lithuania': 'lt',
    'Namibia': 'na', 'Gambia': 'gm', 'Botswana': 'bw', 'Gabon': 'ga', 'Lesotho': 'ls',
    'Slovenia': 'si', 'Latvia': 'lv', 'Bahrain': 'bh', 'North Macedonia': 'mk',
    'Trinidad and Tobago': 'tt', 'Estonia': 'ee', 'Mauritius': 'mu', 'Cyprus': 'cy',
    'Eswatini': 'sz', 'Djibouti': 'dj', 'Fiji': 'fj', 'Comoros': 'km', 'Guyana': 'gy',
    'Bhutan': 'bt', 'Solomon Islands': 'sb', 'Luxembourg': 'lu', 'Montenegro': 'me',
    'Suriname': 'sr', 'Cape Verde': 'cv', 'Malta': 'mt', 'Belize': 'bz', 'Brunei': 'bn',
    'Bahamas': 'bs', 'Maldives': 'mv', 'Iceland': 'is', 'Vanuatu': 'vu', 'Barbados': 'bb',
    'Sao Tome and Principe': 'st', 'Samoa': 'ws', 'Saint Lucia': 'lc', 'Kiribati': 'ki',
    'Micronesia': 'fm', 'Grenada': 'gd', 'Tonga': 'to', 'Seychelles': 'sc',
    'Saint Vincent and the Grenadines': 'vc', 'Antigua and Barbuda': 'ag', 'Andorra': 'ad',
    'Dominica': 'dm', 'Saint Kitts and Nevis': 'kn', 'Monaco': 'mc', 'Liechtenstein': 'li',
    'San Marino': 'sm', 'Palau': 'pw', 'Tuvalu': 'tv', 'Nauru': 'nr',
    'Palestine': 'ps', 'Puerto Rico': 'pr'
}

# ---------------------------------------------------------------------------
# Merge in EVERY ISO-3166 country from utils.flags.
# ---------------------------------------------------------------------------
# The hand-written map above was missing Japan, China, Mexico, Kenya, and many
# others, so `get_countries_list()` never offered them and searching "Japan"
# returned "No country found" even with a fully connected panel.  We now add
# every country the flag resolver knows about (198 of them).
try:
    from utils.flags import _COUNTRIES as _FLAG_COUNTRIES

    for _iso2, _names in _FLAG_COUNTRIES.items():
        for _nm in _names:
            COUNTRY_TO_LZT.setdefault(_nm, _iso2)
except Exception as _merge_ex:  # pragma: no cover - defensive
    logger.warning(f"country merge from utils.flags failed: {_merge_ex}")

# Reverse mapping: code -> Country name
LZT_TO_COUNTRY = {v: k for k, v in COUNTRY_TO_LZT.items()}

def get_lzt_code(country_name):
    if not country_name:
        return None

    clean = str(country_name).strip()
    lower = clean.lower()

    if clean in COUNTRY_TO_LZT:
        return COUNTRY_TO_LZT[clean]

    for name, code in COUNTRY_TO_LZT.items():
        if name.lower() == lower:
            return code

    if len(lower) == 2 and lower.isalpha():
        return lower

    phone_codes = {
        "91": "in",
        "92": "pk",
        "880": "bd",
        "44": "gb",
        "1": "us",
        "27": "za",
        "55": "br",
        "234": "ng",
        "63": "ph",
        "20": "eg",
        "90": "tr",
        "49": "de",
        "33": "fr",
        "39": "it",
        "81": "jp",
        "82": "kr",
        "86": "cn",
        "7": "ru",
    }

    phone = lower.replace("+", "").replace(" ", "").replace("-", "")
    if phone in phone_codes:
        return phone_codes[phone]

    # Final fallback: the universal resolver (ISO-3, aliases, any dial code).
    try:
        from utils.country_search import resolve_country
        resolved = resolve_country(clean)
        if resolved:
            return resolved["iso2"]
    except Exception:
        pass
    return None

def get_country_from_lzt(code):
    if not code: return "Unknown"
    return LZT_TO_COUNTRY.get(code.lower(), code.upper())


# ---------------------------------------------------------------------------
# ISO 3166-1 alpha-2 -> alpha-3
# ---------------------------------------------------------------------------
# The LZT Market `country[]` filter ONLY accepts ISO-3166 alpha-3 codes in
# UPPERCASE (e.g. IND, USA, GBR).  Sending alpha-2 codes (IN, US, GB) makes the
# API silently return an empty result set, which is why "search country" showed
# no cheap accounts.  We keep the human-friendly alpha-2 map above for display
# and convert to alpha-3 here before talking to the API.
ISO2_TO_ISO3 = {
    'ad': 'AND', 'ae': 'ARE', 'af': 'AFG', 'ag': 'ATG', 'al': 'ALB', 'am': 'ARM', 'ao': 'AGO', 'ar': 'ARG', 'at': 'AUT', 'au': 'AUS',
    'az': 'AZE', 'ba': 'BIH', 'bb': 'BRB', 'bd': 'BGD', 'be': 'BEL', 'bg': 'BGR', 'bh': 'BHR', 'bi': 'BDI', 'bj': 'BEN', 'bn': 'BRN',
    'bo': 'BOL', 'br': 'BRA', 'bs': 'BHS', 'bt': 'BTN', 'bw': 'BWA', 'by': 'BLR', 'bz': 'BLZ', 'ca': 'CAN', 'cg': 'COG', 'ch': 'CHE',
    'ci': 'CIV', 'cl': 'CHL', 'cm': 'CMR', 'co': 'COL', 'cr': 'CRI', 'cu': 'CUB', 'cv': 'CPV', 'cy': 'CYP', 'cz': 'CZE', 'de': 'DEU',
    'dj': 'DJI', 'dk': 'DNK', 'dm': 'DMA', 'do': 'DOM', 'dz': 'DZA', 'ec': 'ECU', 'ee': 'EST', 'eg': 'EGY', 'er': 'ERI', 'es': 'ESP',
    'fi': 'FIN', 'fj': 'FJI', 'fm': 'FSM', 'fr': 'FRA', 'ga': 'GAB', 'gb': 'GBR', 'gd': 'GRD', 'ge': 'GEO', 'gh': 'GHA', 'gm': 'GMB',
    'gr': 'GRC', 'gt': 'GTM', 'gy': 'GUY', 'hk': 'HKG', 'hn': 'HND', 'hr': 'HRV', 'ht': 'HTI', 'hu': 'HUN', 'id': 'IDN', 'ie': 'IRL',
    'il': 'ISR', 'in': 'IND', 'iq': 'IRQ', 'ir': 'IRN', 'is': 'ISL', 'it': 'ITA', 'jm': 'JAM', 'jo': 'JOR', 'jp': 'JPN', 'kg': 'KGZ',
    'kh': 'KHM', 'ki': 'KIR', 'km': 'COM', 'kn': 'KNA', 'kp': 'PRK', 'kr': 'KOR', 'kw': 'KWT', 'kz': 'KAZ', 'la': 'LAO', 'lb': 'LBN',
    'lc': 'LCA', 'li': 'LIE', 'lk': 'LKA', 'lr': 'LBR', 'ls': 'LSO', 'lt': 'LTU', 'lu': 'LUX', 'lv': 'LVA', 'ly': 'LBY', 'ma': 'MAR',
    'mc': 'MCO', 'me': 'MNE', 'mg': 'MDG', 'mk': 'MKD', 'mm': 'MMR', 'mn': 'MNG', 'mt': 'MLT', 'mu': 'MUS', 'mv': 'MDV', 'my': 'MYS',
    'mz': 'MOZ', 'na': 'NAM', 'ng': 'NGA', 'ni': 'NIC', 'nl': 'NLD', 'no': 'NOR', 'np': 'NPL', 'nr': 'NRU', 'nz': 'NZL', 'om': 'OMN',
    'pa': 'PAN', 'pe': 'PER', 'pg': 'PNG', 'ph': 'PHL', 'pk': 'PAK', 'pl': 'POL', 'pr': 'PRI', 'ps': 'PSE', 'pt': 'PRT', 'pw': 'PLW',
    'py': 'PRY', 'qa': 'QAT', 'ro': 'ROU', 'rs': 'SRB', 'ru': 'RUS', 'rw': 'RWA', 'sa': 'SAU', 'sb': 'SLB', 'sc': 'SYC', 'se': 'SWE',
    'sg': 'SGP', 'si': 'SVN', 'sk': 'SVK', 'sl': 'SLE', 'sm': 'SMR', 'sn': 'SEN', 'so': 'SOM', 'sr': 'SUR', 'ss': 'SSD', 'st': 'STP',
    'sv': 'SLV', 'sz': 'SWZ', 'td': 'TCD', 'tg': 'TGO', 'th': 'THA', 'tj': 'TJK', 'tm': 'TKM', 'tn': 'TUN', 'to': 'TON', 'tr': 'TUR',
    'tt': 'TTO', 'tv': 'TUV', 'tw': 'TWN', 'ua': 'UKR', 'us': 'USA', 'uy': 'URY', 'uz': 'UZB', 'vc': 'VCT', 've': 'VEN', 'vn': 'VNM',
    'vu': 'VUT', 'ws': 'WSM', 'ye': 'YEM', 'za': 'ZAF', 'zm': 'ZMB', 'zw': 'ZWE',
}
ISO3_TO_ISO2 = {v: k for k, v in ISO2_TO_ISO3.items()}

# The exact ISO-3166 alpha-3 codes LZT accepts for the ``country[]`` filter
# (taken from the official OpenAPI spec, component ``country``).  Sending a
# code outside this set makes the API return an empty list instead of an
# error, which used to look like "this country has no stock".  When a country
# resolves to a code that is NOT in here we omit the server-side filter and
# rely on the tolerant client-side country check instead.
LZT_SUPPORTED_ISO3 = set("""
ABW AGO ALB AND ANT ARE ARG ATA AUS AUT BDI BEL BFA BGD BGR BHR BHS BIH BLR
BLZ BOL BRA BRB BRN BTN BWA CAN CHE CHL CIV CMR COD COG COL CRI CUB CYP CZE
DEU DNK DOM DZA ECU EGY ESP EST ETH FIN FJI FRA GAB GBR GEO GHA GIB GLP GRC
GRD GTM GUF GUM GUY HKG HND HRV HTI HUN IDN IMN IND IRL IRN IRQ ISL ISR ITA
JAM JEY JOR JPN KAZ KEN KHM KWT LAO LBN LBY LKA LTU LUX LVA MAC MAR MCO MDG
MDV MEX MKD MLI MLT MMR MNE MNG MRT MTQ MUS MYS NAM NCL NGA NIC NLD NOR NPL
NZL OMN PAK PAN PCN PER PHL POL PRI PRT PRY PSE QAT REU ROU RUS SAU SEN SGP
SLV SRB SUR SVK SVN SWE TGO THA TTO TUN TUR TWN UKR UMI URY USA VEN VIR VNM
ZAF ZMB ZWE
""".split())


def get_lzt_code3(country_name):
    """Resolve any country name / dial code / ISO-2 / ISO-3 to an ISO-3 code.

    Returns ``None`` when the country cannot be resolved (caller should then
    omit the ``country[]`` filter rather than send a bogus value).
    """
    if not country_name:
        return None

    raw = str(country_name).strip()
    upper = raw.upper()

    # Already an ISO-3 code?
    if len(upper) == 3 and upper.isalpha() and upper in ISO3_TO_ISO2:
        return upper

    code2 = get_lzt_code(country_name)
    if code2:
        code2 = str(code2).strip().lower()
        if code2 in ISO2_TO_ISO3:
            return ISO2_TO_ISO3[code2]
    return None

DC_IPS = {
    1: '149.154.175.50',
    2: '149.154.167.51',
    3: '149.154.175.100',
    4: '149.154.167.91',
    5: '91.108.56.130'
}

def extract_telethon_string_session(item_dict):
    """Robustly extracts Telethon StringSession from any LZT item representation."""
    if not isinstance(item_dict, dict):
        return None
    try:
        import struct, socket, base64
        login_data = item_dict.get('loginData') or {}
        raw = login_data.get('raw') or item_dict.get('raw') or ''
        auth_key_hex = None
        dc_id = None
        
        login_val = str(login_data.get('login') or '').strip()

        # Resolve the DC id from `raw` ("keyhex:dc_id") or telegram_dc_id.
        # The old code used loginData.password (the 2FA password!) as the DC id,
        # which forced every purchased session onto DC 2 and made it fail to
        # connect.  Never use the password here.
        raw_dc = None
        if raw:
            raw_clean = raw.replace('%3A', ':')
            if ':' in raw_clean:
                _, d_str = raw_clean.split(':', 1)
                try:
                    raw_dc = int(d_str.strip())
                except (TypeError, ValueError):
                    raw_dc = None
        dc_hint = raw_dc or item_dict.get('telegram_dc_id') or 2
        try:
            dc_hint = int(str(dc_hint).strip())
        except (TypeError, ValueError):
            dc_hint = 2

        if len(login_val) == 512:
            auth_key_hex = login_val
            dc_id = dc_hint

        if not auth_key_hex and raw:
            raw_clean = raw.replace('%3A', ':')
            if ':' in raw_clean:
                k_hex, d_str = raw_clean.split(':', 1)
                if len(k_hex.strip()) == 512:
                    auth_key_hex = k_hex.strip()
                    try: dc_id = int(d_str.strip())
                    except: dc_id = dc_hint
                    
        if not auth_key_hex:
            return None
            
        auth_key_bytes = bytes.fromhex(auth_key_hex)
        ip_str = DC_IPS.get(dc_id, '149.154.167.51')
        ip_bytes = socket.inet_aton(ip_str)
        port = 443
        packed = struct.pack('>B4sH', dc_id, ip_bytes, port) + auth_key_bytes
        return '1' + base64.urlsafe_b64encode(packed).decode('ascii')
    except Exception as e:
        logger.error(f"Error extracting telethon session: {e}")
        return None

def lzt_raw_to_string_session(raw_str):
    """Convert LZT auth key string (hex:dc_id) into a valid Telethon StringSession."""
    return extract_telethon_string_session({'raw': raw_str})

class LZTClient:
    # Class-level defaults: every attribute used by the client must exist even
    # if __init__ is bypassed (e.g. an object restored from a cache/old pickle).
    _balance_id = None
    _balance_rub = 0.0
    _balance_usd = 0.0
    _balance_cache_ts = 0.0
    last_total = 0
    last_fallback = False
    country_totals = {}

    def __init__(self):
        # Human-readable reason for the last failed API call, so the UI can
        # tell the admin *why* a search returned nothing instead of silently
        # showing an empty list.
        self.last_error = None
        self.last_status = None
        # Coarse reason for the last failure: auth | access | rate | bad |
        # server | unknown.  The UI uses this to show the *right* fix card
        # (e.g. "buy market access" instead of "your key is invalid").
        self.last_error_kind = None
        self.last_body = ""
        # Server-side total for the last search + per-country totals, used by
        # the country picker to display real live stock counts.
        self.last_total = 0
        self.country_totals = {}

        # Balance cache.  These MUST be initialised here: get_balance_info()
        # reads self._balance_id on its very first line, and a missing
        # attribute raised AttributeError -> the whole search_items() call
        # aborted with "Error fetching LZT year for <country>" and the bot
        # showed "No live accounts found" even when the market had stock.
        self._balance_id = None
        self._balance_rub = 0.0
        self._balance_usd = 0.0
        self._balance_cache_ts = 0.0

    def get_token(self):
        try:
            if cur:
                res = cur.execute("SELECT value FROM settings WHERE key='lzt_api_key'").fetchone()
                if res and res[0]:
                    return res[0]
        except Exception as e:
            logger.error(f"Error fetching token from database: {e}")
        return os.getenv("LZT_API_KEY", "")

    def get_headers(self):
        token = self.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Numbott/1.0"
        }

    async def check_connection(self):
        """Ping LZT with the configured token and return (ok, html_message).

        The old version only hit the undocumented ``/user`` alias with a 15s
        timeout and printed a bare error string, so an invalid token looked
        like a random failure.  This version:

          * uses the documented ``GET /me`` first, falling back to ``/user``
          * gives an actionable message for 401 / 402 / 429
          * shows the account name + balance on success
        """
        token = self.get_token()
        if not token:
            return False, (
                "\u274c <b>LZT API Key not configured.</b>\n\n"
                "Set it in Admin \u2192 LZT Panel Settings \u2192 Set API Key, "
                "or as the <code>LZT_API_KEY</code> environment variable."
            )

        urls = [f"{LZT_BASE_URL}/me", f"{LZT_BASE_URL}/user"]
        last_status = None
        last_body = ""
        try:
            async with aiohttp.ClientSession() as session:
                resp = None
                for url in urls:
                    resp = await session.get(
                        url,
                        headers=self.get_headers(),
                        timeout=aiohttp.ClientTimeout(total=30),
                    )
                    if resp.status != 404:
                        break
                    resp.release()
                async with resp:
                    last_status = resp.status
                    body = await resp.text()
                    last_body = body[:300]

                    if resp.status == 200:
                        try:
                            data = json.loads(body)
                        except Exception:
                            data = {}
                        user = data.get("user", {}) or {}
                        username = user.get("username") or "Unknown"
                        balance = user.get("balance")
                        currency = user.get("currency", "RUB")
                        lines = [
                            "\u2705 <b>Connected to LZT Market!</b>",
                            f"\U0001F464 User: <b>{html_escape(username)}</b>",
                        ]
                        if balance is not None:
                            lines.append(
                                f"\U0001F4B0 Balance: <b>{html_escape(str(balance))} "
                                f"{html_escape(str(currency))}</b>"
                            )
                        return True, "\n".join(lines)

                    if resp.status == 401:
                        return False, (
                            "\u274c <b>LZT API key is invalid or expired.</b>\n\n"
                            "LZT answered: <i>Invalid or expired access token</i>.\n\n"
                            "<b>Fix:</b>\n"
                            "1. Open lolz.live \u2192 Account \u2192 API \u2192 "
                            "Get Access Token\n"
                            "2. Make sure the <b>market</b> scope is ticked\n"
                            "3. Copy the fresh token and set it here with "
                            "<b>Set API Key</b>\n\n"
                            "<i>Tokens are revoked the moment you regenerate "
                            "them, so an old copy stops working.</i>"
                        )

                    if resp.status == 402:
                        return False, (
                            "\u26a0\ufe0f <b>LZT Market API access denied (402).</b>\n\n"
                            "Your LZT account needs <b>200 sympathies</b> or an "
                            "active paid subscription to use the Market API."
                        )

                    if resp.status == 429:
                        retry = resp.headers.get("Retry-After", "60")
                        return False, (
                            "\u23f1\ufe0f <b>LZT rate limit hit (429).</b>\n\n"
                            f"Retry after ~{html_escape(str(retry))} seconds. "
                            "Lower <b>Max Pages</b> in Search & Quality Settings "
                            "if this happens often."
                        )

                    if resp.status == 403:
                        kind, message = classify_lzt_error(resp.status, body)
                        if kind == "access":
                            return False, (
                                "\U0001F6A7 <b>Market Access Required.</b>\n\n"
                                "Your key is valid, but LZT refuses Market "
                                "search for this account. LZT requires "
                                "<b>200 sympathies</b> or an active <b>paid "
                                "monthly subscription</b>.\n\n"
                                "<i>" + html_escape(body[:200]) + "</i>"
                            )
                        return False, (
                            "\u26d4 <b>LZT says 403 Forbidden.</b>\n\n"
                            "The token is valid but lacks the <b>market</b> "
                            "scope. Regenerate it with the market scope "
                            "enabled.\n\n<i>" + html_escape(body[:200]) + "</i>"
                        )

                    return False, (
                        f"\u26a0\ufe0f <b>LZT error (HTTP {last_status}).</b>\n"
                        f"<code>{html_escape(last_body[:200])}</code>"
                    )
        except asyncio.TimeoutError:
            return False, (
                "\u23f1\ufe0f <b>LZT did not respond in time.</b>\n\n"
                "The API can be slow; please press Test again."
            )
        except Exception as e:
            logger.error(f"LZT check connection error: {e}")
            return False, (
                f"\u274c <b>Network error connecting to LZT:</b> "
                f"{html_escape(str(e))}"
            )

    async def get_available_countries(self):
        url = f"{LZT_BASE_URL}/telegram"
        params = {
            "order_by": "price_to_up"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.get_headers(), params=params, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        country_counts = {}
                        for item in items:
                            c_code = (item.get("telegram_country") or item.get("country") or "").lower()
                            if c_code:
                                c_name = get_country_from_lzt(c_code)
                                country_counts[c_name] = country_counts.get(c_name, 0) + 1
                        return country_counts
        except Exception as e:
            logger.error(f"LZT get countries error: {e}")
        return {}
    async def get_country_counts(self, max_pages=2):
        """Aggregate live item counts per country from the global cheap list.

        Used to show honest stock numbers on the country picker instead of a
        hard-coded '40+'.  Best-effort: returns {} on any failure.
        """
        counts = {}
        after = None
        for _ in range(max_pages):
            params = {"order_by": "price_to_up"}
            if after:
                params["after"] = after
            data = await self._get_telegram_page(params)
            if not data:
                break
            items = data.get("items") or []
            for it in items:
                raw = str(it.get("telegram_country") or it.get("country") or "").strip()
                if not raw:
                    continue
                key = raw.lower()
                if raw.upper() in ISO3_TO_ISO2:
                    key = ISO3_TO_ISO2[raw.upper()]
                # Keyed by ISO-2 code so the caller can match any country alias.
                counts[key] = counts.get(key, 0) + 1
            after = data.get("nextCursor") or data.get("after")
            if not data.get("hasNextPage") or not after:
                break
        return counts

    async def get_balance_info(self, max_age=600):
        """Return (balance_id, balance_rub, balance_usd).

        The result is cached for ``max_age`` seconds (default 10 min) so the
        hot search path does not make an extra /user request on every call.
        Pass ``max_age=0`` to force a refresh.
        """
        now = time.monotonic()
        if (
            self._balance_id is not None
            and max_age
            and (now - self._balance_cache_ts) < max_age
        ):
            return self._balance_id, self._balance_rub, self._balance_usd

        # The official OpenAPI spec exposes the profile at GET /me (UserModel).
        # /user is a legacy alias that is not documented, so try /me first and
        # fall back to /user only if /me is unavailable.
        urls = [f"{LZT_BASE_URL}/me", f"{LZT_BASE_URL}/user"]

        try:
            async with aiohttp.ClientSession() as session:
                resp = None
                for url in urls:
                    resp = await session.get(
                        url,
                        headers=self.get_headers(),
                        timeout=aiohttp.ClientTimeout(total=15),
                    )
                    if resp.status != 404:
                        break
                    # Release the 404 response before trying the next URL.
                    resp.release()
                async with resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        user = data.get("user", {})
                        balances = user.get("balances", [])

                        balance_id = None
                        balance_rub = 0.0
                        balance_usd = 0.0

                        for b in balances:
                            if b.get("type") == "account":
                                balance_id = b.get("balance_id")
                                balance_rub = float(b.get("balance", 0))
                                balance_usd = float(
                                    b.get("convertedBalance", 0)
                                )
                                break

                        if not balance_id:
                            balance_usd = float(user.get("balance", 0))
                            balance_rub = balance_usd * 84.0

                        self._balance_id = balance_id
                        self._balance_rub = balance_rub
                        self._balance_usd = balance_usd
                        self._balance_cache_ts = time.monotonic()
                        return balance_id, balance_rub, balance_usd

                    # Any non-200 (401 bad key, 402 subscription, 429 rate
                    # limit, 5xx) used to fall through the function and return
                    # None, which then blew up the caller's tuple unpacking and
                    # killed the search.  Always return a 3-tuple.
                    body = ""
                    try:
                        body = await resp.text()
                    except Exception:
                        pass
                    self.last_status = resp.status
                    logger.error(
                        f"LZT profile endpoint returned HTTP {resp.status}: {body[:200]}"
                    )
                    if self._balance_id is not None:
                        return (
                            self._balance_id,
                            self._balance_rub,
                            self._balance_usd,
                        )
                    return None, 0.0, 0.0

        except Exception as e:
            logger.error(f"LZT balance info error: {e}")
            if self._balance_id is not None:
                return self._balance_id, self._balance_rub, self._balance_usd
            return None, 0.0, 0.0

    async def get_balance_rub(self):
        _, bal_rub, _ = await self.get_balance_info()
        return bal_rub

    async def _throttle(self):
        """Reserve the next 3s slot for a Category Search call (20 req/min).

        The lock is only held while computing/reserving the slot, never during
        the sleep.  Holding it during the sleep serialised every concurrent
        user and made the bot look frozen when several people searched at once.
        """
        global _LZT_LAST_CALL
        async with _LZT_SEARCH_LOCK:
            now = time.monotonic()
            slot = max(now, _LZT_LAST_CALL + _LZT_MIN_INTERVAL)
            _LZT_LAST_CALL = slot
        wait = slot - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _get_telegram_page(self, params, retries=2):
        """GET /telegram with 429 handling. Returns parsed JSON or None.

        Uses a long per-request timeout because LZT explicitly recommends
        300s+ for category search; a 20s cap was silently killing real
        searches and making the market look empty.
        """
        url = f"{LZT_BASE_URL}/telegram"
        for attempt in range(retries):
            await self._throttle()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        headers=self.get_headers(),
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=_LZT_REQUEST_TIMEOUT),
                    ) as resp:
                        if resp.status == 429:
                            retry_after = resp.headers.get("Retry-After")
                            try:
                                delay = float(retry_after) if retry_after else 5.0 * (attempt + 1)
                            except (TypeError, ValueError):
                                delay = 5.0 * (attempt + 1)
                            logger.warning(f"LZT rate limit (429), sleeping {delay:.0f}s")
                            await asyncio.sleep(delay)
                            continue
                        if resp.status == 200:
                            self.last_error = None
                            self.last_error_kind = None
                            self.last_status = 200
                            data = await resp.json(content_type=None)
                            # Prove in the Railway logs what LZT actually
                            # returned.  Without this a silent client-side
                            # filter looked identical to an empty market.
                            try:
                                items = (data or {}).get("items") or []
                                sample = ""
                                if items and isinstance(items[0], dict):
                                    first = items[0]
                                    sample = (
                                        f" first(item_id={first.get('item_id')}, "
                                        f"country={first.get('telegram_country')!r}, "
                                        f"spam={first.get('telegram_spam_block')!r}, "
                                        f"price={first.get('price')!r})"
                                    )
                                logger.info(
                                    f"LZT /telegram 200: totalItems="
                                    f"{(data or {}).get('totalItems')} "
                                    f"items={len(items)} params="
                                    f"{ {k: v for k, v in (params or {}).items() if k != 'after'} }"
                                    f"{sample}"
                                )
                            except Exception:
                                pass
                            return data
                        body = await resp.text()
                        self.last_status = resp.status
                        self.last_body = body[:500]
                        kind, message = classify_lzt_error(resp.status, body)
                        self.last_error_kind = kind
                        self.last_error = message
                        logger.error(
                            f"LZT /telegram {resp.status} [{kind}]: {body[:300]}"
                        )
                        if 400 <= resp.status < 500:
                            return None
            except asyncio.TimeoutError:
                logger.warning(f"LZT /telegram timeout (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"LZT /telegram error: {e}")
            await asyncio.sleep(2)
        return None

    def _parse_item(self, item, balance_id=None):
        """Normalise a raw LZT item into the dict the bot uses."""
        if not isinstance(item, dict):
            return None
        try:
            price_rub = item.get("rub_price")
            if price_rub is None:
                price_rub = item.get("price", 0)
            price_rub = float(price_rub or 0)

            pwd_val = (
                item.get("telegram_password_value")
                or item.get("telegram_password")
                or item.get("password")
                or "None"
            )
            has_pwd = bool(pwd_val and str(pwd_val) not in ("0", "None", "False", "none"))

            has_mail = bool(
                item.get("mail")
                or item.get("telegram_email")
                or item.get("email_type") in ("native", "domain", "temporary")
            )
            is_prem = bool(item.get("telegram_premium") or item.get("premium"))

            try:
                stars_cnt = int(
                    item.get("telegram_stars")
                    or item.get("telegram_stars_count")
                    or item.get("stars")
                    or 0
                )
            except (TypeError, ValueError):
                stars_cnt = 0

            dc_val = (
                item.get("telegram_dc_id")
                or item.get("telegram_dc")
                or item.get("dc")
            )

            spam_flag = item.get("telegram_spam_block")
            # LZT returns a real boolean (or -1 when unknown).  The old check
            # `spam_flag != -1` treated False as spam (because False != -1),
            # which silently hid every clean account from the Non-Spam filter.
            spam_known = spam_flag is not None and spam_flag != -1
            is_spam = bool(spam_flag) if spam_known else False

            created_ts = (
                item.get("telegram_session_created_at")
                or item.get("telegram_register_date")
                or item.get("register_date")
                or 0
            )
            # Never fabricate a specific year (the old code hard-coded 2026,
            # which mis-grouped every account whose creation date was absent).
            # Use the real timestamp when present, otherwise fall back to the
            # current year so the item is still shown under a sane bucket.
            item_year = datetime.datetime.now().year
            year_known = False
            try:
                created_ts = int(created_ts or 0)
            except (TypeError, ValueError):
                created_ts = 0
            if created_ts > 1000000:
                try:
                    item_year = datetime.datetime.fromtimestamp(created_ts).year
                    year_known = True
                except Exception:
                    item_year = datetime.datetime.now().year
            elif 1900 < created_ts < 2100:
                item_year = created_ts
                year_known = True

            return {
                "item_id": item.get("item_id"),
                "price_rub": price_rub,
                "price_usd": float(item.get("price", 0) or 0),
                "price_str": str(item.get("price", "0.1")),
                "balance_id": balance_id,
                "phone": item.get("telegram_phone") or item.get("phone") or "Hidden",
                "year": item_year,
                "year_known": year_known,
                "title": item.get("title", ""),
                "has_2fa": has_pwd,
                "twofa_pass": str(pwd_val) if has_pwd else "None",
                "has_email": has_mail,
                "is_premium": is_prem,
                "stars": stars_cnt,
                "dc_id": dc_val,
                "spam_known": spam_known,
                "is_spam": is_spam,
                "country": (item.get("telegram_country") or item.get("country") or ""),
            }
        except Exception as e:
            logger.debug(f"LZT parse item failed: {e}")
            return None

    async def search_items(self, country_name, year=None, limit=None, mode='bulk', max_pages=None):
        """Search live LZT Telegram accounts with the correct server-side filters.

        Fixes the "no cheap accounts" bug:
          * country[]  -> ISO-3 UPPERCASE (IND / USA / GBR ...), not ISO-2
          * spam=no    -> good quality / non-spam  (mode='nonspam')
          * spam=yes   -> cheap spam-blocked       (mode='spam')
          * password / premium / dc_id[] / min_stars for the matching filters
        Pages through `after` cursors (respecting the 20 req/min limit) so year
        filtering and stock counts see real data instead of only page 1.

        The whole search is wrapped in a hard timeout so a slow/looping API can
        never freeze a handler, and the country filter is only sent when LZT
        actually supports the code (unsupported codes silently return []).
        """
        c3 = get_lzt_code3(country_name)
        c2 = get_lzt_code(country_name)

        self.last_error = None
        self.last_error_kind = None
        self.last_body = ""
        self.last_status = None
        self.last_total = 0
        self.last_fallback = False

        if not self.get_token():
            self.last_error = (
                "LZT API key is not configured. Set it in the admin panel "
                "(LZT API Key) or as the LZT_API_KEY environment variable."
            )
            logger.error("LZT search aborted: no API key")
            return []

        # Only send country[] when LZT supports the resolved code.  Unknown or
        # unsupported codes make the API return an empty list, which used to
        # look like "this country has no stock".  In that case we omit the
        # server-side filter and rely on the tolerant client-side check.
        send_country_filter = bool(c3 and c3 in LZT_SUPPORTED_ISO3)
        if c3 and not send_country_filter:
            logger.info(
                f"LZT search: '{country_name}' -> {c3} is not in LZT's country "
                "enum; omitting country[] and filtering client-side"
            )

        # ------------------------------------------------------------------
        # Admin-controlled behaviour (see utils/search_settings.py)
        # ------------------------------------------------------------------
        # `mode` here is the *logical* mode coming from the UI ("nonspam" =
        # Good Quality button, "spam" = Cheap button, "bulk" = everything).
        # resolve_mode() lets the admin map those buttons onto any real filter
        # (e.g. make BOTH buttons return cheap spam-blocked stock).
        effective_mode = resolve_mode(mode) or mode
        order_by = resolve_order(mode) or "price_to_up"
        pmin, pmax = price_bounds()

        if limit is None:
            limit = int_setting("max_results", 50)
        if max_pages is None:
            max_pages = int_setting("max_pages", 4)

        base_params = {"order_by": order_by}
        if send_country_filter:
            base_params["country[]"] = c3

        def _num(v):
            return str(int(v)) if float(v) == int(v) else str(v)

        if pmin:
            base_params["pmin"] = _num(pmin)
        if pmax:
            base_params["pmax"] = _num(pmax)

        if effective_mode == 'spam':
            base_params["spam"] = "yes"
        elif effective_mode == 'nonspam':
            base_params["spam"] = "no"
            # Official param: "Allow geo spam block in search with spam=no".
            # Without it LZT hides every geo-spam-blocked account from the
            # Good Quality list, which is why whole countries looked empty.
            if allow_geo_spam():
                base_params["allow_geo_spamblock"] = "true"

        if effective_mode == 'no_2fa':
            base_params["password"] = "no"
        elif effective_mode == 'with_2fa':
            base_params["password"] = "yes"

        if effective_mode == 'premium':
            base_params["premium"] = "yes"

        if effective_mode == 'no_email':
            base_params["email"] = "no"
        elif effective_mode == 'with_email':
            base_params["email"] = "yes"

        if effective_mode == 'dc5':
            base_params["dc_id[]"] = "5"

        if effective_mode == 'stars':
            base_params["min_stars"] = "1"

        if effective_mode == 'aged':
            # "Aged / old accounts": session created at least 6 months ago.
            # session_age_period must be sent too (day|month|year), otherwise
            # the API cannot interpret session_age.
            base_params["session_age"] = "6"
            base_params["session_age_period"] = "month"

        # ------------------------------------------------------------------
        # Balance: NEVER awaited on the search hot path.
        # ------------------------------------------------------------------
        # fast-buy only needs the wallet id as a tag; it is not required for
        # *finding* stock.  The old code awaited /user with a 20s timeout
        # before every single search, which is exactly why the bot kept
        # timing out and showing "no live accounts".  We now use whatever is
        # already cached and refresh it in the background instead.
        balance_id = self._balance_id
        if balance_id is None:
            try:
                asyncio.create_task(self.get_balance_info())
            except Exception:
                pass

        async def _run(search_params, relax=False, page_cap=None):
            results = []
            after = None
            pages = 0
            cap = page_cap or max_pages
            while pages < cap:
                params = dict(search_params)
                if after:
                    params["after"] = after

                data = await self._get_telegram_page(params)
                if not data:
                    break

                items = data.get("items") or []
                # Remember the server-side total so the country picker can
                # show real live counts instead of a sampled guess.
                try:
                    total = int(data.get("totalItems") or 0)
                    if total:
                        self.last_total = total
                        self.country_totals[country_name] = total
                except Exception:
                    pass
                if not items:
                    break

                for raw in items:
                    parsed = self._parse_item(raw, balance_id)
                    if not parsed:
                        continue

                    # Tolerant country check.  LZT may report the country as
                    # ISO-2 ("in"), ISO-3 ("IND") or a name ("India"), and the
                    # exact format is undocumented.  We only DROP an item when
                    # its country resolves to a *different* known country;
                    # unknown/unparseable values are kept so we never silently
                    # discard real stock.
                    if c2 and parsed["country"]:
                        try:
                            from utils.country_search import (
                                country_matches,
                                resolve_country,
                            )
                            item_c = str(parsed["country"]).strip()
                            if not country_matches(item_c, c2, c3 or "", country_name):
                                resolved_item = resolve_country(item_c)
                                if resolved_item and resolved_item.get("iso2"):
                                    continue
                        except Exception:
                            item_c = str(parsed["country"]).lower()
                            if item_c not in {c2, (c3 or "").lower()}:
                                continue

                    # Only reject an item when we actually know its year and it
                    # differs from the requested one.  Dropping items whose year
                    # is unknown (missing telegram_session_created_at) silently
                    # emptied whole searches.
                    if (
                        year is not None
                        and parsed.get("year_known")
                        and str(parsed["year"]) != str(year)
                    ):
                        continue

                    # Client-side safety for filters the API may not have
                    # applied.  IMPORTANT: only drop an item when we *know* its
                    # spam state is wrong.  LZT reports ``telegram_spam_block``
                    # as -1 / null for a large share of listings (meaning "not
                    # checked"), and the old "strict" rule dropped every one of
                    # those -- which emptied whole countries even though the
                    # API had already applied spam=no/spam=yes server-side.
                    if not relax:
                        if effective_mode == 'nonspam':
                            if parsed["spam_known"] and parsed["is_spam"]:
                                continue
                        if effective_mode == 'spam':
                            if parsed["spam_known"] and not parsed["is_spam"]:
                                continue
                    if effective_mode == 'no_email' and parsed["has_email"]:
                        continue
                    if effective_mode == 'with_email' and not parsed["has_email"]:
                        continue
                    if effective_mode == 'premium' and not parsed["is_premium"]:
                        continue
                    if effective_mode == 'stars' and parsed["stars"] <= 0:
                        continue
                    if effective_mode == 'dc5' and str(parsed["dc_id"]) != '5':
                        continue
                    if effective_mode == 'no_2fa' and parsed["has_2fa"]:
                        continue
                    if effective_mode == 'with_2fa' and not parsed["has_2fa"]:
                        continue

                    results.append(parsed)
                    if len(results) >= limit:
                        return results

                pages += 1
                after = data.get("nextCursor") or data.get("after")
                if not data.get("hasNextPage") or not after:
                    break

            return results

        # Generous hard timeout: 4 pages at the documented 3s spacing plus
        # network latency needs well over 30s, and the old 30s cap was cutting
        # searches off mid-flight (returning [] -> "no live accounts").
        # Budget must exceed the per-request timeout, otherwise a single slow
        # page can trip the outer wait_for before aiohttp gives up.
        budget = max(70, 30 + 50 * int(max_pages or 1))
        try:
            results = await asyncio.wait_for(_run(base_params), timeout=budget)
        except asyncio.TimeoutError:
            self.last_error = (
                "LZT search timed out. Please try again, or lower the number "
                "of pages in Admin > Search & Quality Settings."
            )
            logger.warning(f"LZT search_items hard timeout ({budget}s)")
            return []

        # ------------------------------------------------------------------
        # Country-filter fallback.  LZT's ``country[]`` enum is not always in
        # sync with what sellers pick, and a stale/unsupported value makes the
        # API return an empty page for a country that clearly has stock.  When
        # the country-filtered search comes back empty (but the request itself
        # succeeded) retry once *without* ``country[]`` and keep only items
        # whose country really matches, client-side.
        # ------------------------------------------------------------------
        if not results and send_country_filter and self.last_status == 200:
            logger.info(
                f"LZT search: 0 items for country[]={c3} ('{country_name}'); "
                "retrying without the country filter"
            )
            no_country = {k: v for k, v in base_params.items() if k != "country[]"}
            try:
                results = await asyncio.wait_for(
                    _run(no_country, relax=False, page_cap=2), timeout=60
                )
                if results:
                    self.last_fallback = True
                    logger.info(
                        f"LZT search: country filter bypass recovered "
                        f"{len(results)} item(s) for '{country_name}'"
                    )
            except asyncio.TimeoutError:
                logger.warning("LZT country-filter fallback timeout")
                results = []

        # ------------------------------------------------------------------
        # Auto-fallback: a filtered search that comes back empty is usually a
        # filter problem, not an empty market.  Retry once with the spam and
        # price filters relaxed so the user sees real live stock instead of a
        # misleading "no accounts found" card.
        # ------------------------------------------------------------------
        if not results and auto_fallback() and (
            base_params.get("spam")
            or base_params.get("allow_geo_spamblock")
            or base_params.get("pmin")
            or base_params.get("pmax")
        ):
            relaxed = dict(base_params)
            for k in ("spam", "allow_geo_spamblock", "pmin", "pmax"):
                relaxed.pop(k, None)
            logger.info(
                f"LZT search: no results for '{country_name}' with filters; "
                "retrying with relaxed spam/price filters"
            )
            # Fallback only needs to prove stock exists, so cap it at 2 pages
            # and keep the wait short.
            fb_cap = min(int(max_pages or 1), 2)
            fb_budget = max(45, 20 + 15 * fb_cap)
            try:
                results = await asyncio.wait_for(
                    _run(relaxed, relax=True, page_cap=fb_cap), timeout=fb_budget
                )
                if results:
                    self.last_fallback = True
            except asyncio.TimeoutError:
                logger.warning("LZT search_items fallback timeout")
                results = []

        return results

    async def fast_buy(self, item_id, price_str, balance_id=None):
        """Buy an item via POST /{item_id}/fast-buy.

        Official spec notes implemented here:
          * ``price`` is a JSON *number* (current price in your currency), not
            a string.
          * "If you receive a ``retry_request`` error, you should repeat the
            same request (up to a maximum of 100 times)."  We honour that loop.
          * The successful ``BuyItem`` payload exposes the login as ``login``
            and the 2FA password as ``loginData.password`` -- NOT
            ``telegram_phone`` / ``telegram_password_value`` (those only exist
            on the search list, never on the purchase response).
        """
        url = f"{LZT_BASE_URL}/{item_id}/fast-buy"
        if balance_id is None:
            # Never let a balance hiccup block the purchase itself.
            try:
                bid, _, _ = await asyncio.wait_for(
                    self.get_balance_info(), timeout=20
                )
                balance_id = bid
            except Exception as exc:
                logger.warning(f"LZT balance lookup before fast-buy failed: {exc}")
                balance_id = None

        # `price` must be a number per the OpenAPI schema.
        try:
            price_num = float(price_str)
        except (TypeError, ValueError):
            price_num = price_str

        payload = {"price": price_num}
        if balance_id:
            payload["balance_id"] = balance_id

        MAX_RETRIES = 100
        last_err = "Failed to purchase"

        try:
            async with aiohttp.ClientSession() as session:
                for attempt in range(MAX_RETRIES):
                    async with session.post(
                        url, headers=self.get_headers(), json=payload, timeout=25
                    ) as resp:
                        try:
                            data_json = await resp.json(content_type=None)
                        except Exception:
                            data_json = {}

                        errors = data_json.get("errors") or []
                        if isinstance(errors, str):
                            errors = [errors]
                        err_text = " ".join(str(e) for e in errors).lower()

                        # Documented transient condition: repeat the same
                        # request (up to 100 times).  Back off briefly so we
                        # do not hammer the API.
                        if "retry_request" in err_text or (
                            resp.status == 429
                        ):
                            last_err = "retry_request"
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(min(1.0 + attempt * 0.1, 5.0))
                                continue
                            break

                        if resp.status == 200 and not errors:
                            item = data_json.get("item", {}) or {}
                            login_data = item.get("loginData") or {}

                            # Phone: the purchase response uses `login`.
                            phone = (
                                item.get("login")
                                or item.get("telegram_phone")
                                or item.get("phone")
                                or ""
                            )
                            str_sess = extract_telethon_string_session(item)

                            # 2FA password lives in loginData.password.
                            pwd = (
                                login_data.get("password")
                                or item.get("telegram_password_value")
                                or item.get("telegram_password")
                                or item.get("password")
                                or "None"
                            )
                            pwd_ok = bool(
                                pwd
                                and str(pwd).strip().lower()
                                not in ("0", "none", "false", "")
                            )
                            return True, {
                                "item_id": item_id,
                                "phone": str(phone).strip(),
                                "string_session": str_sess,
                                "twofa": str(pwd) if pwd_ok else "None",
                                "item_data": item,
                            }

                        last_err = (
                            errors[0]
                            if isinstance(errors, list) and errors
                            else (f"HTTP {resp.status}" if resp.status != 200 else "Failed to purchase")
                        )
                        return False, f"{last_err}"

            return False, f"{last_err}"
        except Exception as e:
            logger.error(f"LZT fast_buy error for {item_id}: {e}")
            return False, f"Network error during purchase: {str(e)}"

    async def get_otp_code(self, item_id):
        url = f"{LZT_BASE_URL}/{item_id}/telegram-login-code"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self.get_headers(),
                    timeout=30
                ) as resp:

                    data = await resp.json(content_type=None)

                    if resp.status == 200:
                        # Official TgCodeModel: {"codes": {"code": "...", "date": ...}, "item": {...}}
                        codes = data.get("codes") or {}
                        code = (
                            (codes.get("code") if isinstance(codes, dict) else None)
                            or data.get("code")
                            or data.get("sms_code")
                            or data.get("telegram_code")
                        )

                        if code:
                            return str(code).strip()

                    logger.error(
                        f"LZT OTP error {resp.status}: {data}"
                    )

        except Exception as e:
            logger.error(
                f"LZT OTP request error for {item_id}: {e}"
            )

        return None

lzt_client = LZTClient()

# ==========================================
# LZT Search Module (Added at the end)
# ==========================================

COUNTRY_EMOJI_MAP = {
    'af': {'name': 'Afghanistan', 'flag': '🇦🇫', 'code': '+93'},
    'al': {'name': 'Albania', 'flag': '🇦🇱', 'code': '+355'},
    'dz': {'name': 'Algeria', 'flag': '🇩🇿', 'code': '+213'},
    'ad': {'name': 'Andorra', 'flag': '🇦🇩', 'code': '+376'},
    'ao': {'name': 'Angola', 'flag': '🇦🇴', 'code': '+244'},
    'ag': {'name': 'Antigua and Barbuda', 'flag': '🇦🇬', 'code': '+1-268'},
    'ar': {'name': 'Argentina', 'flag': '🇦🇷', 'code': '+54'},
    'am': {'name': 'Armenia', 'flag': '🇦🇲', 'code': '+374'},
    'au': {'name': 'Australia', 'flag': '🇦🇺', 'code': '+61'},
    'at': {'name': 'Austria', 'flag': '🇦🇹', 'code': '+43'},
    'az': {'name': 'Azerbaijan', 'flag': '🇦🇿', 'code': '+994'},
    'bs': {'name': 'Bahamas', 'flag': '🇧🇸', 'code': '+1-242'},
    'bh': {'name': 'Bahrain', 'flag': '🇧🇭', 'code': '+973'},
    'bd': {'name': 'Bangladesh', 'flag': '🇧🇩', 'code': '+880'},
    'bb': {'name': 'Barbados', 'flag': '🇧🇧', 'code': '+1-246'},
    'by': {'name': 'Belarus', 'flag': '🇧🇾', 'code': '+375'},
    'be': {'name': 'Belgium', 'flag': '🇧🇪', 'code': '+32'},
    'bz': {'name': 'Belize', 'flag': '🇧🇿', 'code': '+501'},
    'bj': {'name': 'Benin', 'flag': '🇧🇯', 'code': '+229'},
    'bt': {'name': 'Bhutan', 'flag': '🇧🇹', 'code': '+975'},
    'bo': {'name': 'Bolivia', 'flag': '🇧🇴', 'code': '+591'},
    'ba': {'name': 'Bosnia and Herzegovina', 'flag': '🇧🇦', 'code': '+387'},
    'bw': {'name': 'Botswana', 'flag': '🇧🇼', 'code': '+267'},
    'br': {'name': 'Brazil', 'flag': '🇧🇷', 'code': '+55'},
    'bn': {'name': 'Brunei', 'flag': '🇧🇳', 'code': '+673'},
    'bg': {'name': 'Bulgaria', 'flag': '🇧🇬', 'code': '+359'},
    'bf': {'name': 'Burkina Faso', 'flag': '🇧🇫', 'code': '+226'},
    'bi': {'name': 'Burundi', 'flag': '🇧🇮', 'code': '+257'},
    'cv': {'name': 'Cabo Verde', 'flag': '🇨🇻', 'code': '+238'},
    'kh': {'name': 'Cambodia', 'flag': '🇰🇭', 'code': '+855'},
    'cm': {'name': 'Cameroon', 'flag': '🇨🇲', 'code': '+237'},
    'ca': {'name': 'Canada', 'flag': '🇨🇦', 'code': '+1'},
    'cf': {'name': 'Central African Republic', 'flag': '🇨🇫', 'code': '+236'},
    'td': {'name': 'Chad', 'flag': '🇹🇩', 'code': '+235'},
    'cl': {'name': 'Chile', 'flag': '🇨🇱', 'code': '+56'},
    'cn': {'name': 'China', 'flag': '🇨🇳', 'code': '+86'},
    'co': {'name': 'Colombia', 'flag': '🇨🇴', 'code': '+57'},
    'km': {'name': 'Comoros', 'flag': '🇰🇲', 'code': '+269'},
    'cg': {'name': 'Congo', 'flag': '🇨🇬', 'code': '+242'},
    'cd': {'name': 'Congo (DRC)', 'flag': '🇨🇩', 'code': '+243'},
    'cr': {'name': 'Costa Rica', 'flag': '🇨🇷', 'code': '+506'},
    'ci': {'name': 'Ivory Coast', 'flag': '🇨🇮', 'code': '+225'},
    'hr': {'name': 'Croatia', 'flag': '🇭🇷', 'code': '+385'},
    'cu': {'name': 'Cuba', 'flag': '🇨🇺', 'code': '+53'},
    'cy': {'name': 'Cyprus', 'flag': '🇨🇾', 'code': '+357'},
    'cz': {'name': 'Czech Republic', 'flag': '🇨🇿', 'code': '+420'},
    'dk': {'name': 'Denmark', 'flag': '🇩🇰', 'code': '+45'},
    'dj': {'name': 'Djibouti', 'flag': '🇩🇯', 'code': '+253'},
    'dm': {'name': 'Dominica', 'flag': '🇩🇲', 'code': '+1-767'},
    'do': {'name': 'Dominican Republic', 'flag': '🇩🇴', 'code': '+1-809'},
    'ec': {'name': 'Ecuador', 'flag': '🇪🇨', 'code': '+593'},
    'eg': {'name': 'Egypt', 'flag': '🇪🇬', 'code': '+20'},
    'sv': {'name': 'El Salvador', 'flag': '🇸🇻', 'code': '+503'},
    'gq': {'name': 'Equatorial Guinea', 'flag': '🇬🇶', 'code': '+240'},
    'er': {'name': 'Eritrea', 'flag': '🇪🇷', 'code': '+291'},
    'ee': {'name': 'Estonia', 'flag': '🇪🇪', 'code': '+372'},
    'sz': {'name': 'Eswatini', 'flag': '🇸🇿', 'code': '+268'},
    'et': {'name': 'Ethiopia', 'flag': '🇪🇹', 'code': '+251'},
    'fj': {'name': 'Fiji', 'flag': '🇫🇯', 'code': '+679'},
    'fi': {'name': 'Finland', 'flag': '🇫🇮', 'code': '+358'},
    'fr': {'name': 'France', 'flag': '🇫🇷', 'code': '+33'},
    'ga': {'name': 'Gabon', 'flag': '🇬🇦', 'code': '+241'},
    'gm': {'name': 'Gambia', 'flag': '🇬🇲', 'code': '+220'},
    'ge': {'name': 'Georgia', 'flag': '🇬🇪', 'code': '+995'},
    'de': {'name': 'Germany', 'flag': '🇩🇪', 'code': '+49'},
    'gh': {'name': 'Ghana', 'flag': '🇬🇭', 'code': '+233'},
    'gr': {'name': 'Greece', 'flag': '🇬🇷', 'code': '+30'},
    'gd': {'name': 'Grenada', 'flag': '🇬🇩', 'code': '+1-473'},
    'gt': {'name': 'Guatemala', 'flag': '🇬🇹', 'code': '+502'},
    'gn': {'name': 'Guinea', 'flag': '🇬🇳', 'code': '+224'},
    'gw': {'name': 'Guinea-Bissau', 'flag': '🇬🇼', 'code': '+245'},
    'gy': {'name': 'Guyana', 'flag': '🇬🇾', 'code': '+592'},
    'ht': {'name': 'Haiti', 'flag': '🇭🇹', 'code': '+509'},
    'hn': {'name': 'Honduras', 'flag': '🇭🇳', 'code': '+504'},
    'hk': {'name': 'Hong Kong', 'flag': '🇭🇰', 'code': '+852'},
    'hu': {'name': 'Hungary', 'flag': '🇭🇺', 'code': '+36'},
    'is': {'name': 'Iceland', 'flag': '🇮🇸', 'code': '+354'},
    'in': {'name': 'India', 'flag': '🇮🇳', 'code': '+91'},
    'id': {'name': 'Indonesia', 'flag': '🇮🇩', 'code': '+62'},
    'ir': {'name': 'Iran', 'flag': '🇮🇷', 'code': '+98'},
    'iq': {'name': 'Iraq', 'flag': '🇮🇶', 'code': '+964'},
    'ie': {'name': 'Ireland', 'flag': '🇮🇪', 'code': '+353'},
    'il': {'name': 'Israel', 'flag': '🇮🇱', 'code': '+972'},
    'it': {'name': 'Italy', 'flag': '🇮🇹', 'code': '+39'},
    'jm': {'name': 'Jamaica', 'flag': '🇯🇲', 'code': '+1-876'},
    'jp': {'name': 'Japan', 'flag': '🇯🇵', 'code': '+81'},
    'jo': {'name': 'Jordan', 'flag': '🇯🇴', 'code': '+962'},
    'kz': {'name': 'Kazakhstan', 'flag': '🇰🇿', 'code': '+7'},
    'ke': {'name': 'Kenya', 'flag': '🇰🇪', 'code': '+254'},
    'ki': {'name': 'Kiribati', 'flag': '🇰🇮', 'code': '+686'},
    'kp': {'name': 'North Korea', 'flag': '🇰🇵', 'code': '+850'},
    'kr': {'name': 'South Korea', 'flag': '🇰🇷', 'code': '+82'},
    'kw': {'name': 'Kuwait', 'flag': '🇰🇼', 'code': '+965'},
    'kg': {'name': 'Kyrgyzstan', 'flag': '🇰🇬', 'code': '+996'},
    'la': {'name': 'Laos', 'flag': '🇱🇦', 'code': '+856'},
    'lv': {'name': 'Latvia', 'flag': '🇱🇻', 'code': '+371'},
    'lb': {'name': 'Lebanon', 'flag': '🇱🇧', 'code': '+961'},
    'ls': {'name': 'Lesotho', 'flag': '🇱🇸', 'code': '+266'},
    'lr': {'name': 'Liberia', 'flag': '🇱🇷', 'code': '+231'},
    'ly': {'name': 'Libya', 'flag': '🇱🇾', 'code': '+218'},
    'li': {'name': 'Liechtenstein', 'flag': '🇱🇮', 'code': '+423'},
    'lt': {'name': 'Lithuania', 'flag': '🇱🇹', 'code': '+370'},
    'lu': {'name': 'Luxembourg', 'flag': '🇱🇺', 'code': '+352'},
    'mo': {'name': 'Macau', 'flag': '🇲🇴', 'code': '+853'},
    'mg': {'name': 'Madagascar', 'flag': '🇲🇬', 'code': '+261'},
    'mw': {'name': 'Malawi', 'flag': '🇲🇼', 'code': '+265'},
    'my': {'name': 'Malaysia', 'flag': '🇲🇾', 'code': '+60'},
    'mv': {'name': 'Maldives', 'flag': '🇲🇻', 'code': '+960'},
    'ml': {'name': 'Mali', 'flag': '🇲🇱', 'code': '+223'},
    'mt': {'name': 'Malta', 'flag': '🇲🇹', 'code': '+356'},
    'mh': {'name': 'Marshall Islands', 'flag': '🇲🇭', 'code': '+692'},
    'mr': {'name': 'Mauritania', 'flag': '🇲🇷', 'code': '+222'},
    'mu': {'name': 'Mauritius', 'flag': '🇲🇺', 'code': '+230'},
    'mx': {'name': 'Mexico', 'flag': '🇲🇽', 'code': '+52'},
    'fm': {'name': 'Micronesia', 'flag': '🇫🇲', 'code': '+691'},
    'md': {'name': 'Moldova', 'flag': '🇲🇩', 'code': '+373'},
    'mc': {'name': 'Monaco', 'flag': '🇲🇨', 'code': '+377'},
    'mn': {'name': 'Mongolia', 'flag': '🇲🇳', 'code': '+976'},
    'me': {'name': 'Montenegro', 'flag': '🇲🇪', 'code': '+382'},
    'ma': {'name': 'Morocco', 'flag': '🇲🇦', 'code': '+212'},
    'mz': {'name': 'Mozambique', 'flag': '🇲🇿', 'code': '+258'},
    'mm': {'name': 'Myanmar', 'flag': '🇲🇲', 'code': '+95'},
    'na': {'name': 'Namibia', 'flag': '🇳🇦', 'code': '+264'},
    'nr': {'name': 'Nauru', 'flag': '🇳🇷', 'code': '+674'},
    'np': {'name': 'Nepal', 'flag': '🇳🇵', 'code': '+977'},
    'nl': {'name': 'Netherlands', 'flag': '🇳🇱', 'code': '+31'},
    'nz': {'name': 'New Zealand', 'flag': '🇳🇿', 'code': '+64'},
    'ni': {'name': 'Nicaragua', 'flag': '🇳🇮', 'code': '+505'},
    'ne': {'name': 'Niger', 'flag': '🇳🇪', 'code': '+227'},
    'ng': {'name': 'Nigeria', 'flag': '🇳🇬', 'code': '+234'},
    'no': {'name': 'Norway', 'flag': '🇳🇴', 'code': '+47'},
    'om': {'name': 'Oman', 'flag': '🇴🇲', 'code': '+968'},
    'pk': {'name': 'Pakistan', 'flag': '🇵🇰', 'code': '+92'},
    'pw': {'name': 'Palau', 'flag': '🇵🇼', 'code': '+680'},
    'ps': {'name': 'Palestine', 'flag': '🇵🇸', 'code': '+970'},
    'pa': {'name': 'Panama', 'flag': '🇵🇦', 'code': '+507'},
    'pg': {'name': 'Papua New Guinea', 'flag': '🇵🇬', 'code': '+675'},
    'py': {'name': 'Paraguay', 'flag': '🇵🇾', 'code': '+595'},
    'pe': {'name': 'Peru', 'flag': '🇵🇪', 'code': '+51'},
    'ph': {'name': 'Philippines', 'flag': '🇵🇭', 'code': '+63'},
    'pl': {'name': 'Poland', 'flag': '🇵🇱', 'code': '+48'},
    'pt': {'name': 'Portugal', 'flag': '🇵🇹', 'code': '+351'},
    'qa': {'name': 'Qatar', 'flag': '🇶🇦', 'code': '+974'},
    'ro': {'name': 'Romania', 'flag': '🇷🇴', 'code': '+40'},
    'ru': {'name': 'Russia', 'flag': '🇷🇺', 'code': '+7'},
    'rw': {'name': 'Rwanda', 'flag': '🇷🇼', 'code': '+250'},
    'kn': {'name': 'Saint Kitts and Nevis', 'flag': '🇰🇳', 'code': '+1-869'},
    'lc': {'name': 'Saint Lucia', 'flag': '🇱🇨', 'code': '+1-758'},
    'vc': {'name': 'Saint Vincent and the Grenadines', 'flag': '🇻🇨', 'code': '+1-784'},
    'ws': {'name': 'Samoa', 'flag': '🇼🇸', 'code': '+685'},
    'sm': {'name': 'San Marino', 'flag': '🇸🇲', 'code': '+378'},
    'st': {'name': 'Sao Tome and Principe', 'flag': '🇸🇹', 'code': '+239'},
    'sa': {'name': 'Saudi Arabia', 'flag': '🇸🇦', 'code': '+966'},
    'sn': {'name': 'Senegal', 'flag': '🇸🇳', 'code': '+221'},
    'rs': {'name': 'Serbia', 'flag': '🇷🇸', 'code': '+381'},
    'sc': {'name': 'Seychelles', 'flag': '🇸🇨', 'code': '+248'},
    'sl': {'name': 'Sierra Leone', 'flag': '🇸🇱', 'code': '+232'},
    'sg': {'name': 'Singapore', 'flag': '🇸🇬', 'code': '+65'},
    'sk': {'name': 'Slovakia', 'flag': '🇸🇰', 'code': '+421'},
    'si': {'name': 'Slovenia', 'flag': '🇸🇮', 'code': '+386'},
    'sb': {'name': 'Solomon Islands', 'flag': '🇸🇧', 'code': '+677'},
    'so': {'name': 'Somalia', 'flag': '🇸🇴', 'code': '+252'},
    'za': {'name': 'South Africa', 'flag': '🇿🇦', 'code': '+27'},
    'ss': {'name': 'South Sudan', 'flag': '🇸🇸', 'code': '+211'},
    'es': {'name': 'Spain', 'flag': '🇪🇸', 'code': '+34'},
    'lk': {'name': 'Sri Lanka', 'flag': '🇱🇰', 'code': '+94'},
    'sd': {'name': 'Sudan', 'flag': '🇸🇩', 'code': '+249'},
    'sr': {'name': 'Suriname', 'flag': '🇸🇷', 'code': '+597'},
    'se': {'name': 'Sweden', 'flag': '🇸🇪', 'code': '+46'},
    'ch': {'name': 'Switzerland', 'flag': '🇨🇭', 'code': '+41'},
    'sy': {'name': 'Syria', 'flag': '🇸🇾', 'code': '+963'},
    'tw': {'name': 'Taiwan', 'flag': '🇹🇼', 'code': '+886'},
    'tj': {'name': 'Tajikistan', 'flag': '🇹🇯', 'code': '+992'},
    'tz': {'name': 'Tanzania', 'flag': '🇹🇿', 'code': '+255'},
    'th': {'name': 'Thailand', 'flag': '🇹🇭', 'code': '+66'},
    'tl': {'name': 'Timor-Leste', 'flag': '🇹🇱', 'code': '+670'},
    'tg': {'name': 'Togo', 'flag': '🇹🇬', 'code': '+228'},
    'to': {'name': 'Tonga', 'flag': '🇹🇴', 'code': '+676'},
    'tt': {'name': 'Trinidad and Tobago', 'flag': '🇹🇹', 'code': '+1-868'},
    'tn': {'name': 'Tunisia', 'flag': '🇹🇳', 'code': '+216'},
    'tr': {'name': 'Turkey', 'flag': '🇹🇷', 'code': '+90'},
    'tm': {'name': 'Turkmenistan', 'flag': '🇹🇲', 'code': '+993'},
    'tv': {'name': 'Tuvalu', 'flag': '🇹🇻', 'code': '+688'},
    'ug': {'name': 'Uganda', 'flag': '🇺🇬', 'code': '+256'},
    'ua': {'name': 'Ukraine', 'flag': '🇺🇦', 'code': '+380'},
    'ae': {'name': 'UAE', 'flag': '🇦🇪', 'code': '+971'},
    'gb': {'name': 'United Kingdom', 'flag': '🇬🇧', 'code': '+44'},
    'us': {'name': 'USA', 'flag': '🇺🇸', 'code': '+1'},
    'uy': {'name': 'Uruguay', 'flag': '🇺🇾', 'code': '+598'},
    'uz': {'name': 'Uzbekistan', 'flag': '🇺🇿', 'code': '+998'},
    'vu': {'name': 'Vanuatu', 'flag': '🇻🇺', 'code': '+678'},
    'va': {'name': 'Vatican City', 'flag': '🇻🇦', 'code': '+379'},
    've': {'name': 'Venezuela', 'flag': '🇻🇪', 'code': '+58'},
    'vn': {'name': 'Vietnam', 'flag': '🇻🇳', 'code': '+84'},
    'ye': {'name': 'Yemen', 'flag': '🇾🇪', 'code': '+967'},
    'zm': {'name': 'Zambia', 'flag': '🇿🇲', 'code': '+260'},
    'zw': {'name': 'Zimbabwe', 'flag': '🇿🇼', 'code': '+263'}
}

class LZTSearchModule:
    def __init__(self, api_token: str = None):
        self.client = LZTClient()

    async def search_accounts(self, category: str = "telegram", params: dict = None) -> list:
        """
        Searches items from LZT market with specific category and filters, 
        and automatically maps country flag, name, and phone code.
        """
        if params is None:
            params = {}
            
        url = f"{LZT_BASE_URL}/{category}"
        headers = self.client.get_headers()
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("items", [])
                        
                        processed_items = []
                        for item in items:
                            c_code = (item.get("telegram_country") or item.get("country") or "").lower()
                            
                            if c_code in COUNTRY_EMOJI_MAP:
                                item["country_info"] = COUNTRY_EMOJI_MAP[c_code]
                            else:
                                item["country_info"] = {
                                    "name": c_code.upper() if c_code else "Unknown", 
                                    "flag": "🏳️", 
                                    "code": ""
                                }
                                
                            processed_items.append(item)
                            
                        return processed_items
                    else:
                        logger.error(f"Failed to fetch LZT items. Status: {response.status}")
                        return []
            except Exception as e:
                logger.error(f"LZT Search Module Exception: {e}")
                return []
