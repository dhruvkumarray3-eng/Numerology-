import os
import time
import datetime
import aiohttp
import asyncio
import json
import logging
from config import logger
from database import cur, db, get_flag_by_country_name

LZT_BASE_URL = "https://api.lzt.market"

# Category Search allows 20 requests/minute -> keep a global 3s gap.
_LZT_SEARCH_LOCK = asyncio.Lock()
_LZT_LAST_CALL = 0.0
_LZT_MIN_INTERVAL = 3.0

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
        if len(login_val) == 512:
            auth_key_hex = login_val
            dc_val = login_data.get('password') or item_dict.get('telegram_dc_id') or 2
            try: dc_id = int(str(dc_val).strip())
            except: dc_id = 2
            
        if not auth_key_hex and raw:
            raw_clean = raw.replace('%3A', ':')
            if ':' in raw_clean:
                k_hex, d_str = raw_clean.split(':', 1)
                if len(k_hex.strip()) == 512:
                    auth_key_hex = k_hex.strip()
                    try: dc_id = int(d_str.strip())
                    except: dc_id = 2
                    
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
    def __init__(self):
        # Human-readable reason for the last failed API call, so the UI can
        # tell the admin *why* a search returned nothing instead of silently
        # showing an empty list.
        self.last_error = None
        self.last_status = None

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
        token = self.get_token()
        if not token:
            return False, "❌ LZT API Key not configured."
        
        url = f"{LZT_BASE_URL}/user"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.get_headers(), timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        user = data.get("user", {})
                        username = user.get("username", "Unknown")
                        balance = user.get("balance", 0)
                        currency = user.get("currency", "RUB")
                        return True, f"✅ Connected to LZT!\n👤 User: <b>{username}</b>\n💰 Balance: <b>{balance} {currency}</b>"
                    else:
                        try:
                            err_data = await resp.json()
                            errors = err_data.get("errors", [])
                            err_str = ", ".join(errors) if isinstance(errors, list) else str(errors)
                            return False, f"❌ LZT Error: {err_str}"
                        except:
                            text = await resp.text()
                            return False, f"⚠️ LZT Error (Status {resp.status}): {text[:100]}"
        except Exception as e:
            logger.error(f"LZT check connection error: {e}")
            return False, f"❌ Network error connecting to LZT: {str(e)}"

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

        url = f"{LZT_BASE_URL}/user"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self.get_headers(),
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
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

    async def _get_telegram_page(self, params, retries=3):
        """GET /telegram with 429 handling. Returns parsed JSON or None."""
        url = f"{LZT_BASE_URL}/telegram"
        for attempt in range(retries):
            await self._throttle()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, headers=self.get_headers(), params=params, timeout=20
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
                            self.last_status = 200
                            return await resp.json(content_type=None)
                        body = await resp.text()
                        self.last_status = resp.status
                        if resp.status in (401, 403):
                            self.last_error = (
                                "LZT API key rejected (401/403). Add a valid "
                                "market-scope key with /setlzt or LZT_API_KEY."
                            )
                        elif resp.status == 402:
                            self.last_error = (
                                "LZT says your account needs 200 sympathies or a "
                                "paid subscription to use Market search."
                            )
                        elif resp.status == 429:
                            self.last_error = "LZT rate limit hit (429). Try again in a minute."
                        else:
                            self.last_error = f"LZT /telegram returned {resp.status}: {body[:160]}"
                        logger.error(f"LZT /telegram {resp.status}: {body[:200]}")
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
            spam_known = spam_flag is not None
            is_spam = spam_known and spam_flag != -1

            created_ts = (
                item.get("telegram_session_created_at")
                or item.get("telegram_register_date")
                or item.get("register_date")
                or 0
            )
            item_year = 2026
            if created_ts and created_ts > 1000000:
                try:
                    item_year = datetime.datetime.fromtimestamp(int(created_ts)).year
                except Exception:
                    item_year = 2026
            elif created_ts and 1900 < created_ts < 2100:
                item_year = int(created_ts)

            return {
                "item_id": item.get("item_id"),
                "price_rub": price_rub,
                "price_usd": float(item.get("price", 0) or 0),
                "price_str": str(item.get("price", "0.1")),
                "balance_id": balance_id,
                "phone": item.get("telegram_phone") or item.get("phone") or "Hidden",
                "year": item_year,
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

    async def search_items(self, country_name, year=None, limit=20, mode='bulk', max_pages=4):
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
        self.last_status = None

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

        base_params = {"order_by": "price_to_up"}
        if send_country_filter:
            base_params["country[]"] = c3

        if mode == 'spam':
            base_params["spam"] = "yes"
        elif mode == 'nonspam':
            base_params["spam"] = "no"

        if mode == 'no_2fa':
            base_params["password"] = "no"
        elif mode == 'with_2fa':
            base_params["password"] = "yes"

        if mode == 'premium':
            base_params["premium"] = "yes"

        if mode == 'dc5':
            base_params["dc_id[]"] = "5"

        if mode == 'stars':
            base_params["min_stars"] = "1"

        balance_id, _, _ = await self.get_balance_info()

        async def _run():
            results = []
            after = None
            pages = 0
            while pages < max_pages:
                params = dict(base_params)
                if after:
                    params["after"] = after

                data = await self._get_telegram_page(params)
                if not data:
                    break

                items = data.get("items") or []
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

                    if year is not None and str(parsed["year"]) != str(year):
                        continue

                    # Client-side safety for filters the API may not have applied.
                    if mode == 'nonspam' and parsed["spam_known"] and parsed["is_spam"]:
                        continue
                    if mode == 'spam' and parsed["spam_known"] and not parsed["is_spam"]:
                        continue
                    if mode == 'no_email' and parsed["has_email"]:
                        continue
                    if mode == 'with_email' and not parsed["has_email"]:
                        continue
                    if mode == 'premium' and not parsed["is_premium"]:
                        continue
                    if mode == 'stars' and parsed["stars"] <= 0:
                        continue
                    if mode == 'dc5' and str(parsed["dc_id"]) != '5':
                        continue
                    if mode == 'no_2fa' and parsed["has_2fa"]:
                        continue
                    if mode == 'with_2fa' and not parsed["has_2fa"]:
                        continue

                    results.append(parsed)
                    if len(results) >= limit:
                        return results

                pages += 1
                after = data.get("nextCursor") or data.get("after")
                if not data.get("hasNextPage") or not after:
                    break

            return results

        try:
            return await asyncio.wait_for(_run(), timeout=30)
        except asyncio.TimeoutError:
            self.last_error = "LZT search timed out. Please try again in a moment."
            logger.warning("LZT search_items hard timeout (30s)")
            return []

    async def fast_buy(self, item_id, price_str, balance_id=None):
        url = f"{LZT_BASE_URL}/{item_id}/fast-buy"
        if balance_id is None:
            bid, _, _ = await self.get_balance_info()
            balance_id = bid

        payload = {"price": str(price_str)}
        if balance_id:
            payload["balance_id"] = balance_id
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.get_headers(), json=payload, timeout=25) as resp:
                    data_json = await resp.json()
                    if resp.status == 200 and not data_json.get("errors"):
                        item = data_json.get("item", {})
                        phone = item.get("telegram_phone") or item.get("phone") or ""
                        str_sess = extract_telethon_string_session(item)
                        
                        pwd = item.get("telegram_password_value") or item.get("telegram_password") or item.get("password") or item.get("twofa") or "None"
                        return True, {
                            "item_id": item_id,
                            "phone": phone,
                            "string_session": str_sess,
                            "twofa": str(pwd) if (pwd and str(pwd) not in ("0", "None", "False")) else "None",
                            "item_data": item
                        }
                    else:
                        errors = data_json.get("errors", ["Failed to purchase"])
                        err = errors[0] if isinstance(errors, list) and errors else str(errors)
                        return False, f"{err}"
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
                        code = (
                            data.get("code")
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
