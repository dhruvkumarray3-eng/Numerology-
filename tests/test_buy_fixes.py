"""Regression tests for the LZT purchase-flow fixes.

Run from the repository root:

    python3 tests/test_buy_fixes.py

Covers the bugs that made buyers see "Purchase failed" even though the
market purchase succeeded:

  1. ``post_buy_spam_ok`` accepts clean accounts (spam flag 0) in nonspam
     mode -- the old check discarded them.
  2. ``friendly_buy_error`` maps LZT error codes to actionable messages.
  3. ``_parse_item`` never invents a "0.1" price and falls back to
     ``rub_price`` when ``price`` is missing.
  4. ``fast_buy`` sends a numeric price, coerces a string ``balance_id`` to
     int, and omits ``price`` when it is unknown.
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
cfg.logger = logging.getLogger("test_buy_fixes")
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


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1
    print(f"PASS {label}")


# ---------------------------------------------------------------------------
# 1. post_buy_spam_ok
# ---------------------------------------------------------------------------
def test_post_buy_spam_ok():
    # The regression: clean accounts (0) must be delivered in nonspam mode.
    check("nonspam + clean(0) accepted", L.post_buy_spam_ok("nonspam", 0) is True)
    check("nonspam + real spam(-3) rejected", L.post_buy_spam_ok("nonspam", -3) is False)
    check("nonspam + spam days(7) rejected", L.post_buy_spam_ok("nonspam", 7) is False)
    check("nonspam + unknown(-1) accepted", L.post_buy_spam_ok("nonspam", -1) is True)
    check("nonspam + geo(-4) accepted", L.post_buy_spam_ok("nonspam", -4) is True)
    check("nonspam + None accepted", L.post_buy_spam_ok("nonspam", None) is True)
    check("spam + clean(0) rejected", L.post_buy_spam_ok("spam", 0) is False)
    check("spam + real spam(-3) accepted", L.post_buy_spam_ok("spam", -3) is True)
    check("bulk + clean(0) accepted", L.post_buy_spam_ok("bulk", 0) is True)
    check("bulk + spam accepted", L.post_buy_spam_ok("bulk", 5) is True)


# ---------------------------------------------------------------------------
# 2. friendly_buy_error
# ---------------------------------------------------------------------------
def test_friendly_buy_error():
    cases = [
        ("retry_request", "busy"),
        ("not_enough_money", "balance"),
        ("you are blacklisted", "blacklist"),
        ("daily check limit reached", "limit"),
        ("item already sold", "sold"),
        ("item deleted", "no longer exists"),
    ]
    for raw, needle in cases:
        msg = L.friendly_buy_error(400, [raw])
        check(f"friendly({raw!r})", needle in msg.lower(), msg)
    check("401 -> api key", "api key" in L.friendly_buy_error(401, []).lower())
    check("429 -> too many", "too many" in L.friendly_buy_error(429, []).lower())


# ---------------------------------------------------------------------------
# 3. _parse_item price handling
# ---------------------------------------------------------------------------
def test_parse_item_price():
    p = L.lzt_client._parse_item({"item_id": 1, "price": 12.5, "rub_price": 1000})
    check("price_str from price", p["price_str"] == "12.5", p["price_str"])
    check("price_usd is numeric price", p["price_usd"] == 12.5, p["price_usd"])

    p2 = L.lzt_client._parse_item({"item_id": 2, "rub_price": 250})
    check("price_str falls back to rub_price", p2["price_str"] == "250", p2["price_str"])

    p3 = L.lzt_client._parse_item({"item_id": 3})
    check("no fake 0.1 price", p3["price_str"] == "", p3["price_str"])


# ---------------------------------------------------------------------------
# 4. fast_buy payload
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload
        self.headers = {}

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        return str(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _coro(value):
    async def _inner(*a, **k):
        return value

    return _inner


def test_fast_buy_payload():
    ok = FakeResp(
        200,
        {
            "status": "success",
            "item": {
                "item_id": 7,
                "login": "+10000000000",
                "loginData": {"raw": "aa" * 256 + ":2", "password": "pw"},
            },
        },
    )
    sess = FakeSession([ok])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    L.lzt_client.get_balance_info = _coro((None, 0.0, 0.0))

    async def run():
        # String balance id must be coerced to int; empty price omitted.
        return await L.lzt_client.fast_buy(7, "", "12345")

    ok_flag, info = asyncio.run(run())
    check("fast_buy success", ok_flag is True, info)
    payload = sess.calls[-1][2]["json"]
    check("balance_id coerced to int", payload.get("balance_id") == 12345, payload)
    check("unknown price omitted", "price" not in payload, payload)


def main():
    test_post_buy_spam_ok()
    test_friendly_buy_error()
    test_parse_item_price()
    test_fast_buy_payload()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
