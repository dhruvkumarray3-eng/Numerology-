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

    def __await__(self):
        async def _self():
            return self

        return _self().__await__()


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        # Copy the payload: fast_buy mutates the same dict between retries,
        # so storing a reference would rewrite the earlier call's history.
        snapshot = dict(kwargs)
        if isinstance(snapshot.get("json"), dict):
            snapshot["json"] = dict(snapshot["json"])
        self.calls.append(("POST", url, snapshot))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        # Return a FakeResp that is both awaitable and an async context
        # manager: get_balance_info() awaits it, get_otp_code() uses
        # `async with` directly.
        self.calls.append(("GET", url, kwargs))
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

    async def run():
        # String balance id must be coerced to int; empty price omitted.
        return await L.lzt_client.fast_buy(7, "", "12345")

    ok_flag, info = asyncio.run(run())
    check("fast_buy success", ok_flag is True, info)
    payload = sess.calls[-1][2]["json"]
    check("balance_id coerced to int", payload.get("balance_id") == 12345, payload)
    check("unknown price omitted", "price" not in payload, payload)


# ---------------------------------------------------------------------------
# 5. get_balance_info: empty sub-wallet must not hide the main balance
# ---------------------------------------------------------------------------
def test_balance_info_empty_subwallet():
    """Live /me shape: main balance 413 RUB / 5.14 USD, sub-wallet $0.

    The old code reported the empty sub-wallet's 0.00 *and* handed its
    balance_id to fast_buy, which made LZT answer 403 "not enough money".
    """
    me = FakeResp(
        200,
        {
            "user": {
                "balance": 413.0,
                "currency": "usd",
                "convertedBalance": 5.14,
                "balances": [
                    {
                        "type": "account",
                        "balance_id": 264649,
                        "balance": "0.00",
                        "convertedBalance": 0,
                        "fullTitle": "Balance for buying accounts ($0)",
                    }
                ],
            }
        },
    )
    sess = FakeSession([me])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    L.lzt_client._balance_fetched = False
    L.lzt_client._balance_id = None

    bid, rub, usd = asyncio.run(L.lzt_client.get_balance_info(max_age=0))
    check("empty wallet -> no balance_id", bid is None, bid)
    check("main RUB balance reported", abs(rub - 413.0) < 0.01, rub)
    check("main USD balance reported", abs(usd - 5.14) < 0.01, usd)

    # A funded sub-wallet *is* usable.
    me2 = FakeResp(
        200,
        {
            "user": {
                "balance": 0,
                "convertedBalance": 0,
                "balances": [
                    {"type": "account", "balance_id": 999, "balance": "50.00", "convertedBalance": 0.6}
                ],
            }
        },
    )
    L.aiohttp.ClientSession = lambda *a, **k: FakeSession([me2])
    L.lzt_client._balance_fetched = False
    bid2, rub2, usd2 = asyncio.run(L.lzt_client.get_balance_info(max_age=0))
    check("funded wallet -> balance_id kept", bid2 == 999, bid2)
    check("funded wallet amount", abs(usd2 - 0.6) < 0.01, usd2)


# ---------------------------------------------------------------------------
# 6. fast_buy must not invent a balance_id, and must recover from a dead one
# ---------------------------------------------------------------------------
def _ok_resp(item_id=11, phone="918197387243", login="ab" * 256):
    return FakeResp(
        200,
        {
            "status": "ok",
            "item": {
                "item_id": item_id,
                "login": login,
                "telegram_phone": phone,
                "telegram_spam_block": 0,
                "loginData": {"raw": "cd" * 256 + ":5", "password": "pw"},
            },
        },
    )


def test_fast_buy_omits_balance_id():
    sess = FakeSession([_ok_resp()])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    ok, info = asyncio.run(L.lzt_client.fast_buy(11, "0.09", None))
    check("fast_buy without balance_id succeeds", ok is True, info)
    payload = sess.calls[-1][2]["json"]
    check("balance_id not auto-filled", "balance_id" not in payload, payload)
    check("numeric price sent", payload.get("price") == 0.09, payload)


def test_fast_buy_retries_without_dead_wallet():
    dead = FakeResp(
        403,
        {
            "errors": [
                'You do not have enough money to buy this product. '
                '<b><a href="market/balance/deposit">Add credit</a></b>'
            ]
        },
    )
    sess = FakeSession([dead, _ok_resp(12)])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    ok, info = asyncio.run(L.lzt_client.fast_buy(12, "0.09", 264649))
    check("403 on dead wallet is retried", ok is True, info)
    first = sess.calls[0][2]["json"]
    second = sess.calls[-1][2]["json"]
    check("first attempt used the wallet", first.get("balance_id") == 264649, first)
    check("retry dropped the wallet", "balance_id" not in second, second)


def test_fast_buy_retries_with_changed_price():
    """LZT answers 403 "Account price has been changed. Account costs now
    0.15. instead 0.09." -- the bot must retry once with the new price
    instead of telling the buyer the purchase is forbidden."""
    changed = FakeResp(
        403,
        {
            "errors": [
                "Account price has been changed. Account costs now 0.15. "
                "instead 0.09."
            ]
        },
    )
    sess = FakeSession([changed, _ok_resp(14)])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    ok, info = asyncio.run(L.lzt_client.fast_buy(14, "0.09", None))
    check("price change is retried", ok is True, info)
    check("price change retried once", len(sess.calls) == 2, len(sess.calls))
    first = sess.calls[0][2]["json"]
    second = sess.calls[-1][2]["json"]
    check("first attempt used the old price", float(first["price"]) == 0.09, first)
    check("retry used the new price", float(second["price"]) == 0.15, second)

    # The message alone must also be human-readable.
    msg = L.friendly_buy_error(
        403, ["Account price has been changed. Account costs now 0.15."]
    )
    check("price change mapped", "price changed" in msg.lower(), msg)


def test_fast_buy_phone_is_not_the_auth_key():
    """`login` holds the 512-char auth-key hex for Telegram items."""
    sess = FakeSession([_ok_resp(13)])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    ok, info = asyncio.run(L.lzt_client.fast_buy(13, "0.09", None))
    check("buy ok", ok is True, info)
    check("phone is the real number", info.get("phone") == "918197387243", info.get("phone"))
    check("string session built", len(info.get("string_session") or "") > 100, info.get("string_session"))


# ---------------------------------------------------------------------------
# 7. get_otp_code: `codes` is a LIST and stale codes must be ignored
# ---------------------------------------------------------------------------
def test_get_otp_code_list():
    body = {
        "codes": [
            {"code": "11111", "date": 1000},
            {"code": "22222", "date": 3000},
            {"code": "33333", "date": 2000},
        ],
        "item": {"item_id": 5},
    }
    L.aiohttp.ClientSession = lambda *a, **k: FakeSession([FakeResp(200, body)])
    check("newest code picked", asyncio.run(L.lzt_client.get_otp_code(5)) == "22222")

    L.aiohttp.ClientSession = lambda *a, **k: FakeSession([FakeResp(200, body)])
    check("stale codes filtered", asyncio.run(L.lzt_client.get_otp_code(5, since=2500)) == "22222")

    L.aiohttp.ClientSession = lambda *a, **k: FakeSession([FakeResp(200, body)])
    check("no fresh code -> None", asyncio.run(L.lzt_client.get_otp_code(5, since=9000)) is None)

    L.aiohttp.ClientSession = lambda *a, **k: FakeSession([FakeResp(200, {"codes": {"code": "4444"}})])
    check("dict payload still supported", asyncio.run(L.lzt_client.get_otp_code(5)) == "4444")


# ---------------------------------------------------------------------------
# 8. Dead listings + empty network errors
# ---------------------------------------------------------------------------
def test_dead_session_error():
    """LZT answers 403 "Session is invalid (logged out or account is blocked)"
    for dead listings.  It must map to a per-item message, not a generic
    "forbidden", so the buyer understands the bot is moving on."""
    msg = L.friendly_buy_error(403, ["Session is invalid (logged out or account is blocked)"])
    check("dead session mapped", "dead" in msg.lower(), msg)
    check("dead session not generic", "forbidden" not in msg.lower(), msg)
    for variant in ("session invalid", "logged out", "account is blocked"):
        m = L.friendly_buy_error(403, [variant])
        check(f"dead variant {variant!r}", "dead" in m.lower(), m)


def test_empty_network_error():
    """A bare aiohttp exception has an empty str(); the message must still
    say *something* useful instead of trailing off after a colon."""
    class Boom(Exception):
        def __str__(self):
            return ""

    class BoomSession:
        def post(self, *a, **k):
            raise Boom()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    L.aiohttp.ClientSession = lambda *a, **k: BoomSession()
    ok, msg = asyncio.run(L.lzt_client.fast_buy(1, "0.1", None))
    check("network error fails", ok is False)
    check("network error names the exception", "Boom" in msg, msg)
    check("network error not blank", msg.strip().endswith(":") is False, msg)


def main():
    test_post_buy_spam_ok()
    test_friendly_buy_error()
    test_parse_item_price()
    test_fast_buy_payload()
    test_balance_info_empty_subwallet()
    test_fast_buy_omits_balance_id()
    test_fast_buy_retries_without_dead_wallet()
    test_fast_buy_retries_with_changed_price()
    test_fast_buy_phone_is_not_the_auth_key()
    test_get_otp_code_list()
    test_dead_session_error()
    test_empty_network_error()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
