"""Tests for the admin-controlled live-search settings (utils/search_settings.py).

Run from the repository root:

    python3 tests/test_search_settings.py

Covers:
  1. Defaults resolve the way the UI expects (Good = nonspam, Cheap = spam).
  2. "Both cheap" forces the Good button onto the cheap filter.
  3. Per-mode sort orders are honoured.
  4. Price window parsing (empty -> None, numbers -> float).
  5. Invalid values are rejected instead of corrupting the settings table.
  6. search_items() actually sends order_by / spam / pmin / pmax to LZT and
     never blocks on a balance lookup.
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

# ---------------------------------------------------------------------------
# Stub config + an in-memory settings table so no real DB is needed.
# ---------------------------------------------------------------------------
cfg = types.ModuleType("config")
cfg.logger = logging.getLogger("test_search_settings")
cfg.API_ID = 1
cfg.API_HASH = "x"
cfg.BOT_TOKEN = "x"
cfg.LZT_API_KEY = "test-key"
sys.modules["config"] = cfg

STORE = {}


class _Cur:
    rowcount = 0

    def execute(self, sql, params=()):
        s = " ".join(sql.split()).upper()
        if s.startswith("SELECT VALUE FROM SETTINGS"):
            key = params[0]
            val = STORE.get(key)

            class _R:
                def fetchone(self):
                    return (val,) if val is not None else None

                def fetchall(self):
                    return [(val,)] if val is not None else []

            return _R()
        if s.startswith("INSERT OR REPLACE INTO SETTINGS"):
            STORE[params[0]] = params[1]

        class _R:
            def fetchone(self):
                return None

            def fetchall(self):
                return []

        return _R()


dbmod = types.ModuleType("database")
dbmod.cur = _Cur()
dbmod.db = types.SimpleNamespace(commit=lambda: None)
dbmod.get_flag_by_country_name = lambda n: "🏳"
sys.modules["database"] = dbmod

import utils.search_settings as S  # noqa: E402
import utils.lzt as L  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {extra}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. Defaults
# ---------------------------------------------------------------------------
S.reset_search_settings()
check("default good filter", S.resolve_mode("nonspam") == "nonspam", S.resolve_mode("nonspam"))
check("default cheap filter", S.resolve_mode("spam") == "spam", S.resolve_mode("spam"))
check("bulk stays bulk", S.resolve_mode("bulk") == "bulk")
check("default order", S.resolve_order("nonspam") == "price_to_up")
check("default price bounds", S.price_bounds() == (None, None))
check("default max results", S.int_setting("max_results", 1) == 50)
check("default strict spam on", S.is_strict_spam() is True)

# ---------------------------------------------------------------------------
# 2. Both cheap
# ---------------------------------------------------------------------------
S.set_search_setting("both_cheap", "1")
check("both_cheap forces good->cheap", S.resolve_mode("nonspam") == "spam")
S.set_search_setting("cheap_filter", "bulk")
check("both_cheap follows cheap_filter", S.resolve_mode("nonspam") == "bulk")
S.set_search_setting("both_cheap", "0")
check("both_cheap off restores good", S.resolve_mode("nonspam") == "nonspam")

# ---------------------------------------------------------------------------
# 3. Sort orders
# ---------------------------------------------------------------------------
S.set_search_setting("good_order", "pdate_to_down")
S.set_search_setting("cheap_order", "price_to_down")
S.set_search_setting("bulk_order", "pdate_to_up")
check("good order applied", S.resolve_order("nonspam") == "pdate_to_down")
check("cheap order applied", S.resolve_order("spam") == "price_to_down")
check("bulk order applied", S.resolve_order("bulk") == "pdate_to_up")

# ---------------------------------------------------------------------------
# 4. Price window
# ---------------------------------------------------------------------------
S.set_search_setting("min_price", "50")
S.set_search_setting("max_price", "1500")
check("price bounds parsed", S.price_bounds() == (50.0, 1500.0), S.price_bounds())
S.set_search_setting("min_price", "")
check("empty min price cleared", S.price_bounds()[0] is None)

# ---------------------------------------------------------------------------
# 5. Validation
# ---------------------------------------------------------------------------
before = S.get_search_setting("good_filter")
try:
    S.set_search_setting("good_filter", "definitely_not_a_filter")
    rejected = False
except ValueError:
    rejected = True
check("invalid filter rejected", rejected and S.get_search_setting("good_filter") == before,
      S.get_search_setting("good_filter"))
try:
    S.set_search_setting("max_pages", "999")
    rejected_pages = False
except ValueError:
    rejected_pages = True
check("invalid page count rejected", rejected_pages and S.get_search_setting("max_pages") == S.DEFAULTS["max_pages"],
      S.get_search_setting("max_pages"))

# ---------------------------------------------------------------------------
# 6. search_items sends the configured params
# ---------------------------------------------------------------------------
S.reset_search_settings()
S.set_search_setting("both_cheap", "1")
S.set_search_setting("cheap_order", "price_to_down")
S.set_search_setting("min_price", "100")
S.set_search_setting("max_price", "900")
S.set_search_setting("max_pages", "1")

captured = []


async def _fake_page(self, params, retries=3):
    captured.append(dict(params))
    return {
        "items": [
            {
                "item_id": 1,
                "price": 500,
                "rub_price": 500,
                "telegram_country": "IND",
                "telegram_spam_block": 1,
                "telegram_session_created_at": 1700000000,
            }
        ],
        "hasNextPage": False,
        "nextCursor": None,
        "totalItems": 7,
    }


L.lzt_client.get_token = lambda: "test-key"
L.lzt_client._get_telegram_page = types.MethodType(_fake_page, L.lzt_client)
L.lzt_client._balance_id = None

items = asyncio.get_event_loop().run_until_complete(
    L.lzt_client.search_items("India", mode="nonspam")
)

p = captured[0] if captured else {}
check("search sent cheap order", p.get("order_by") == "price_to_down", p.get("order_by"))
check("search sent spam=yes (both cheap)", p.get("spam") == "yes", p.get("spam"))
check("search sent pmin", p.get("pmin") == "100", p.get("pmin"))
check("search sent pmax", p.get("pmax") == "900", p.get("pmax"))
check("search sent ISO-2 country", p.get("country[]") == "IN", p.get("country[]"))
check("search returned item", len(items) == 1, len(items))
check("country total recorded", L.lzt_client.country_totals.get("India") == 7,
      L.lzt_client.country_totals)
check("no balance request on hot path", L.lzt_client._balance_id is None)

# ---------------------------------------------------------------------------
# 7. Geo-spam flag + auto-fallback
# ---------------------------------------------------------------------------
S.reset_search_settings()
check("default allow_geo_spam on", S.allow_geo_spam() is True)
check("default auto_fallback on", S.auto_fallback() is True)
S.set_search_setting("allow_geo_spam", "0")
check("allow_geo_spam toggles off", S.allow_geo_spam() is False)
S.set_search_setting("allow_geo_spam", "1")

captured.clear()
items = asyncio.get_event_loop().run_until_complete(
    L.lzt_client.search_items("India", mode="nonspam")
)
p = captured[0] if captured else {}
check("nonspam sends allow_geo_spamblock", p.get("allow_geo_spamblock") == "true",
      p.get("allow_geo_spamblock"))
check("nonspam sends spam=no", p.get("spam") == "no", p.get("spam"))
check("fallback dropped spam filter", len(captured) > 1 and "spam" not in captured[1],
      captured[1:2])
check("fallback flag set", L.lzt_client.last_fallback is True, L.lzt_client.last_fallback)
check("fallback returned the spam item", len(items) == 1, len(items))

# With auto_fallback OFF an empty filtered search must stay empty.
S.set_search_setting("auto_fallback", "0")
captured.clear()
items = asyncio.get_event_loop().run_until_complete(
    L.lzt_client.search_items("India", mode="nonspam")
)
check("no fallback when disabled", len(captured) == 1, len(captured))
check("no results when fallback disabled", items == [], items)
S.set_search_setting("auto_fallback", "1")

print()
if FAILS:
    print(f"{len(FAILS)} TEST(S) FAILED: {FAILS}")
    sys.exit(1)
print("ALL TESTS PASSED")
