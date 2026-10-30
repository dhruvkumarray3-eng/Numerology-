"""Mocked regression tests for the LZT official-spec compliance fixes (PR #14).

Run from the repository root:

    python3 tests/test_lzt_spec.py

Covers:
  1. get_otp_code reads TgCodeModel {"codes": {"code": ...}}.
  2. fast_buy implements the documented retry_request loop (up to 100x),
     sends a numeric price, and extracts phone from `login` + 2FA from
     `loginData.password`.
  3. extract_telethon_string_session derives the DC from loginData.raw,
     never from the 2FA password.
  4. _parse_item does not hard-code year=2026 and detects telegram_email.
  5. search_items does not drop items whose year is unknown.
"""
import asyncio
import base64
import datetime
import logging
import os
import struct
import sys
import types

# ---------------------------------------------------------------------------
# The bot imports config/database at module import time; stub them so the test
# runs without a real bot token, database file or network access.
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "x")

cfg = types.ModuleType("config")
cfg.logger = logging.getLogger("test_lzt")
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

# Force a token so search_items does not abort early.
L.lzt_client.get_token = lambda: "test-key"


# ---------------------------------------------------------------------------
# Fake aiohttp transport
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

    def release(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._responses.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self._responses.pop(0)


async def _coro(value):
    return value


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
async def test_otp_reads_codes_code():
    """TgCodeModel is {"codes": {"code": ...}} -- not {"code": ...}."""
    sess = FakeSession(
        [FakeResp(200, {"codes": {"code": "54321", "date": 1}, "item": {}})]
    )
    L.aiohttp.ClientSession = lambda *a, **k: sess
    code = await L.lzt_client.get_otp_code(999)
    assert code == "54321", f"OTP got {code!r}"
    print("PASS get_otp_code reads codes.code ->", code)


async def test_fast_buy_retry_and_fields():
    """retry_request is retried; price is numeric; phone/2FA/DC are correct."""
    retry1 = FakeResp(200, {"errors": ["retry_request"]})
    retry2 = FakeResp(200, {"errors": ["retry_request"]})
    ok = FakeResp(
        200,
        {
            "status": "success",
            "item": {
                "item_id": 123,
                "login": "+919876543210",
                "loginData": {
                    "raw": "aa" * 256 + ":4",
                    "login": "bb" * 256,
                    "password": "My2FAPass",
                },
            },
            "system_info": {},
        },
    )
    sess = FakeSession([retry1, retry2, ok])
    L.aiohttp.ClientSession = lambda *a, **k: sess
    L.lzt_client.get_balance_info = lambda *a, **k: _coro((555, 413.0, 5.0))

    ok_flag, info = await L.lzt_client.fast_buy(123, "100.0", 555)
    assert ok_flag, info
    assert info["phone"] == "+919876543210", info["phone"]
    assert info["twofa"] == "My2FAPass", info["twofa"]

    post_call = [c for c in sess.calls if c[0] == "POST"][-1]
    assert isinstance(post_call[2]["json"]["price"], float), post_call[2]["json"]

    packed = base64.urlsafe_b64decode(info["string_session"][1:] + "==")
    dc = struct.unpack(">B", packed[:1])[0]
    assert dc == 4, f"DC should come from raw (4), got {dc}"
    print(
        "PASS fast_buy retry loop ->",
        info["phone"],
        info["twofa"],
        "DC",
        dc,
        post_call[2]["json"],
    )


def test_parse_item_year_email_spam_stars():
    item = {
        "item_id": 1,
        "price": 100,
        "rub_price": 100,
        "telegram_country": "IND",
        "telegram_session_created_at": 1600000000,  # 2020-09-13
        "telegram_email": 1,
        "telegram_password": 0,
        "telegram_spam_block": 0,
        "telegram_stars_count": 5,
        "telegram_dc_id": "2",
        "telegram_premium": 1,
    }
    p = L.lzt_client._parse_item(item)
    assert p["year"] == 2020, p["year"]
    assert p["year_known"] is True
    assert p["has_email"] is True
    assert p["has_2fa"] is False
    assert p["is_spam"] is False and p["spam_known"] is True
    assert p["stars"] == 5 and p["is_premium"] is True

    # Missing session date -> current year (never a hard-coded 2026).
    p2 = L.lzt_client._parse_item({"item_id": 2, "price": 5})
    assert p2["year"] == datetime.datetime.now().year, p2["year"]
    assert p2["year_known"] is False
    print("PASS _parse_item year/email/spam/stars")


async def test_search_keeps_unknown_year_items():
    page = {
        "items": [
            {
                "item_id": 1,
                "price": 10,
                "telegram_country": "IND",
                "telegram_session_created_at": 1600000000,
            },
            {"item_id": 2, "price": 11, "telegram_country": "IND"},
        ],
        "hasNextPage": False,
        "nextCursor": None,
    }
    L.lzt_client.get_balance_info = lambda *a, **k: _coro((1, 100.0, 1.0))

    async def fake_page(params, retries=3):
        return page

    L.lzt_client._get_telegram_page = fake_page
    items = await L.lzt_client.search_items(
        "India", year=2020, mode="bulk", limit=10
    )
    ids = {i["item_id"] for i in items}
    assert 1 in ids, ids
    assert 2 in ids, f"unknown-year item was dropped: {ids}"
    print("PASS search_items keeps unknown-year item ->", ids)


def test_rank_results():
    """Good Quality prefers clean/starred/older; Cheap is cheapest-first."""
    items = [
        {"item_id": 1, "price_usd": 1.0, "stars": 0, "year": 2024, "is_spam": True},
        {"item_id": 2, "price_usd": 5.0, "stars": 100, "year": 2018, "is_spam": False},
        {"item_id": 3, "price_usd": 2.0, "stars": 10, "year": 2022, "is_spam": False},
    ]
    good = L.lzt_client._rank_results(list(items), "nonspam")
    assert [i["item_id"] for i in good] == [2, 3, 1], good
    cheap = L.lzt_client._rank_results(list(items), "spam")
    assert [i["item_id"] for i in cheap] == [1, 3, 2], cheap
    bulk = L.lzt_client._rank_results(list(items), "bulk")
    assert [i["item_id"] for i in bulk] == [1, 2, 3], bulk
    print("PASS _rank_results good/cheap/bulk ordering")


async def main():
    await test_otp_reads_codes_code()
    await test_fast_buy_retry_and_fields()
    test_parse_item_year_email_spam_stars()
    await test_search_keeps_unknown_year_items()
    test_rank_results()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
