"""Regression tests for LZT error classification + spam-filter over-filtering.

Run from the repository root:

    python3 tests/test_lzt_errors.py

Why these exist
---------------
LZT returns **403 for two different problems**: a bad/under-scoped token, and
an account that is not allowed to use the Market API at all ("200 sympathies
or a paid monthly subscription").  The bot used to report both as "API key
invalid", so a valid key on an account without market access looked broken and
every search looked like an empty market.

Also: ``telegram_spam_block`` is -1 / null for many listings ("not checked").
The old "strict" rule dropped every one of those, emptying whole countries.
"""
import asyncio
import logging
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "x")

cfg = types.ModuleType("config")
cfg.logger = logging.getLogger("test_lzt_errors")
cfg.API_ID = 1
cfg.API_HASH = "x"
cfg.BOT_TOKEN = "x"
cfg.LZT_API_KEY = "test-key"
sys.modules["config"] = cfg

dbmod = types.ModuleType("database")


class _Cur:
    rowcount = 0

    def execute(self, *a, **k):
        class _R:
            def fetchone(self):
                return None

            def fetchall(self):
                return []

        return _R()


dbmod.cur = _Cur()
dbmod.db = types.SimpleNamespace(commit=lambda: None)
dbmod.get_flag_by_country_name = lambda n: "🏳"
sys.modules["database"] = dbmod

import utils.lzt as L  # noqa: E402

L.lzt_client.get_token = lambda: "test-key"

PASS = 0


def check(name, cond, extra=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL: {name} {extra}")
    PASS += 1
    print(f"PASS {name}")


# ---------------------------------------------------------------------------
# 1. classify_lzt_error
# ---------------------------------------------------------------------------
print("\n[1] error classification")

kind, msg = L.classify_lzt_error(401, '{"errors":["Invalid or expired access token."]}')
check("401 -> auth", kind == "auth", kind)

kind, msg = L.classify_lzt_error(
    403,
    '{"errors":["To use the Market API, you need to have 200 sympathies, '
    'or you can purchase a monthly subscription."]}',
)
check("403 + sympathies -> access", kind == "access", kind)
check("access message mentions sympathies", "sympathies" in msg.lower())

kind, _ = L.classify_lzt_error(402, "Payment Required")
check("402 -> access", kind == "access", kind)

kind, _ = L.classify_lzt_error(403, '{"errors":["Forbidden"]}')
check("plain 403 -> auth/scope", kind == "auth", kind)

kind, _ = L.classify_lzt_error(429, "Too many requests")
check("429 -> rate", kind == "rate", kind)

kind, _ = L.classify_lzt_error(400, "bad country")
check("400 -> bad", kind == "bad", kind)

kind, _ = L.classify_lzt_error(503, "unavailable")
check("503 -> server", kind == "server", kind)


# ---------------------------------------------------------------------------
# 2. search_items keeps items whose spam state is unknown
# ---------------------------------------------------------------------------
print("\n[2] unknown spam state must not be dropped")

RAW = [
    {"item_id": 1, "price": 1.5, "rub_price": 120.0,
     "telegram_country": "IRN", "telegram_spam_block": -1,
     "telegram_session_created_at": 1700000000},
    {"item_id": 2, "price": 2.0, "rub_price": 160.0,
     "telegram_country": "IRN", "telegram_spam_block": 0,
     "telegram_session_created_at": 1700000000},
]


async def fake_page(params, retries=2):
    L.lzt_client.last_status = 200
    L.lzt_client.last_error = None
    L.lzt_client.last_error_kind = None
    return {"items": RAW, "totalItems": 2, "hasNextPage": False}


L.lzt_client._get_telegram_page = fake_page
L.lzt_client._throttle = lambda: asyncio.sleep(0)

# Force "strict spam" ON: the old bug only appeared with strict enabled.
try:
    import utils.search_settings as SS
    SS.is_strict_spam = lambda *a, **k: True
    L.is_strict_spam = lambda *a, **k: True
except Exception:
    pass

items = asyncio.get_event_loop().run_until_complete(
    L.lzt_client.search_items("Iran", mode="nonspam", limit=10)
)
ids = sorted(i["item_id"] for i in items)
check("unknown-spam item kept", 1 in ids, ids)
check("known-clean item kept", 2 in ids, ids)

# ---------------------------------------------------------------------------
# [2b] LZT spam-block integer codes: -3 = real spam, -4 = geo spam block,
#      -1/None = unknown, 0 = clean, >0 = blocked (days)
# ---------------------------------------------------------------------------
print("\n[2b] spam-block code mapping")
for flag, want_known, want_spam in [
    (-3, True, True), (-4, False, False), (-1, False, False),
    (None, False, False), (0, True, False), (7, True, True),
]:
    p = L.lzt_client._parse_item(
        {"item_id": 9, "price": 1, "rub_price": 1,
         "telegram_country": "IN", "telegram_spam_block": flag}, None
    )
    check(f"spam_block={flag!r} -> known={want_known} spam={want_spam}",
          p["spam_known"] is want_known and p["is_spam"] is want_spam,
          (p["spam_known"], p["is_spam"]))

# Geo-blocked (-4) items must survive the Good Quality (nonspam) filter.
GEO = [{"item_id": 11, "price": 1, "rub_price": 1, "telegram_country": "IN",
        "telegram_spam_block": -4, "telegram_session_created_at": 1700000000}]

async def geo_page(params, retries=2):
    L.lzt_client.last_status = 200
    L.lzt_client.last_error = None
    L.lzt_client.last_error_kind = None
    return {"items": GEO, "totalItems": 1, "hasNextPage": False}

L.lzt_client._get_telegram_page = geo_page
geo_items = asyncio.get_event_loop().run_until_complete(
    L.lzt_client.search_items("India", mode="nonspam", limit=10)
)
check("geo-spam-block item kept in Good Quality",
      any(i["item_id"] == 11 for i in geo_items), geo_items)


# ---------------------------------------------------------------------------
# 3. country-filter fallback recovers stock
# ---------------------------------------------------------------------------
print("\n[3] country[] fallback")

calls = []


async def page_country_empty(params, retries=2):
    calls.append(dict(params))
    L.lzt_client.last_status = 200
    L.lzt_client.last_error = None
    L.lzt_client.last_error_kind = None
    if "country[]" in params:
        return {"items": [], "totalItems": 0, "hasNextPage": False}
    return {"items": RAW, "totalItems": 2, "hasNextPage": False}


L.lzt_client._get_telegram_page = page_country_empty
items = asyncio.get_event_loop().run_until_complete(
    L.lzt_client.search_items("Iran", mode="nonspam", limit=10)
)
check("fallback recovered items", len(items) == 2, len(items))
check("fallback flag set", L.lzt_client.last_fallback is True)
check("country filter was tried first", any("country[]" in c for c in calls))
check("retry without country filter happened", any("country[]" not in c for c in calls))


# ---------------------------------------------------------------------------
# [4] token format validation (Client ID / Secret vs real Access Token)
# ---------------------------------------------------------------------------
print("\n[4] token format validation")

ok, why = L.validate_token_format(
    "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"
)
check("real JWT accepted", ok is True, why)

ok, why = L.validate_token_format("1234")
check("client id rejected", ok is False and "Client ID" in why, why)

ok, why = L.validate_token_format("a" * 64)
check("client secret rejected", ok is False and "Client Secret" in why, why)

ok, why = L.validate_token_format("")
check("empty rejected", ok is False, why)

ok, why = L.validate_token_format(
    "Bearer eyJhbGciOiJSUzUxMiJ9.eyJzdWIiOiIxIn0.sig"
)
check("Bearer prefix tolerated", ok is True, why)

fp = L.token_fingerprint("eyJhbGciOiJSUzUxMiJ9.eyJzdWIiOiIxIn0.sig")
check("fingerprint hides middle", "eyJhbGci" in fp and "len=" in fp, fp)
check("fingerprint of empty", L.token_fingerprint("") == "not set")


# ---------------------------------------------------------------------------
# [5] country[] must be ISO-2 UPPERCASE (live API returns 0 for ISO-3)
# ---------------------------------------------------------------------------
print("\n[5] country code conversion (ISO-2 for the API)")
for name, want in [
    ("India", "IN"), ("USA", "US"), ("United States", "US"), ("Iran", "IR"),
    ("Indonesia", "ID"), ("Morocco", "MA"), ("Turkey", "TR"), ("in", "IN"),
    ("IND", "IN"), ("us", "US"), ("South Korea", "KR"), ("Uzbekistan", "UZ"),
    ("Yemen", "YE"), ("Afghanistan", "AF"), ("Papua New Guinea", "PG"),
]:
    got = L.get_lzt_code2(name)
    check(f"get_lzt_code2({name!r}) == {want}", got == want, got)

check("ISO-3 is never sent to the API", L.get_lzt_code2("USA") == "US")


# ---------------------------------------------------------------------------
# [6] EVERY country in the picker must resolve to an ISO-2 code, because the
#     filter is now sent unconditionally (LZT accepts any valid alpha-2).
# ---------------------------------------------------------------------------
print("\n[6] all countries resolve to ISO-2")
from utils.country_search import all_countries

countries = all_countries()
check("picker has the full ISO-3166 set", len(countries) >= 249, len(countries))

unresolved = [c["name"] for c in countries if not L.get_lzt_code2(c["name"])]
check("no country is left without an ISO-2 code", not unresolved, unresolved[:10])

bad = [c["name"] for c in countries
       if not (L.get_lzt_code2(c["name"]) or "").isalpha()
       or len(L.get_lzt_code2(c["name"]) or "") != 2]
check("every code is exactly 2 letters", not bad, bad[:10])

check("ISO2_TO_ISO3 covers every country",
      len(L.ISO2_TO_ISO3) >= 249, len(L.ISO2_TO_ISO3))

print(f"\nALL {PASS} CHECKS PASSED")
