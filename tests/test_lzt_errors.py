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


print(f"\nALL {PASS} CHECKS PASSED")
