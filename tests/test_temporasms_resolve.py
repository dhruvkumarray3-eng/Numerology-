"""Regression tests for TemporaSMS service resolution + multi-route pricing.

These lock in the fix for the exact error users hit in the All Apps OTP /
Telegram number-change / WhatsApp panels:

    "The panel returned no prices for 'whatsapp' (code s8-a, route 8)."

Root cause: operator 8's catalogue contains a service literally named "A"
(code ``s8-a``).  The old containment check matched "a" inside "whatsapp",
so the WhatsApp panel asked for a code the provider does not sell and got an
empty price table.  The fix has three parts, all covered here:

1. ``_score_name`` never matches when the shorter side is under 3 chars.
2. ``resolve_service`` prefers curated canonical codes (``wqp``/``tvm``).
3. ``_prices_for`` walks ``resolve_candidates`` so a second route can answer.

Run with:

    API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_temporasms_resolve.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test-hash")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("TEMPORASMS_API_KEY", "test-key")
os.environ.setdefault("TEMPORASMS_BASE_URL", "https://api.temporasms.com")

from utils import temporasms as T

CHECKS = []


def check(name, cond, extra=""):
    CHECKS.append((name, bool(cond), extra))
    if not cond:
        print(f"  FAIL {name} {extra}")


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, text, status=200):
        self._text = text
        self.status = status

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, handler, *a, **kw):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, params=None, **kw):
        return _FakeResp(self._handler(params or {}))


def install_fake_calls(handler):
    """Patch the module so every provider call goes through ``handler``."""
    async def fake_call(action, operator=None, **params):
        q = dict(params)
        q["action"] = action
        if operator is not None:
            q["operator"] = operator
        return handler(q), None

    async def fake_call_conn(session, action, operator=None, **params):
        q = dict(params)
        q["action"] = action
        if operator is not None:
            q["operator"] = operator
        return handler(q)

    T._call = fake_call
    T._call_conn = fake_call_conn
    T.aiohttp.ClientSession = lambda *a, **kw: _FakeSession(handler, *a, **kw)


def reset_caches():
    T._CATALOGUE["data"] = {}
    T._CATALOGUE["ts"] = 0.0
    T._COUNTRIES_CACHE.clear()
    T._PRICES_CACHE.clear()
    T._RESOLVED_SERVICE.clear()


COUNTRIES = {"22": "India", "187": "United States", "4": "Philippines"}


# --------------------------------------------------------------------------- #
# 1. name scoring: the "A" bug
# --------------------------------------------------------------------------- #
def test_score_name():
    check("exact match is 100", T._score_name("whatsapp", "whatsapp") == 100)
    check("prefix match high", T._score_name("whatsapp", "WhatsApp Business") >= 90)
    # THE bug: a one-letter service name must never match a long app name.
    check("single letter 'A' never matches whatsapp",
          T._score_name("whatsapp", "A") == 0,
          T._score_name("whatsapp", "A"))
    check("single letter 'A' never matches telegram",
          T._score_name("telegram", "A") == 0)
    check("two letters 'wa' never matches 'A'", T._score_name("wa", "A") == 0)
    check("unrelated word scores 0",
          T._score_name("telegram", "telecharge") == 0,
          T._score_name("telegram", "telecharge"))
    check("compound catalogue name still matches",
          T._score_name("instagram", "Instagram+Threads") >= 75)
    check("tiktok compound matches",
          T._score_name("tiktok", "TikTokDouyin") >= 60)
    check("google bundle matches",
          T._score_name("google", "Google, Gmail, Youtube") >= 75)


# --------------------------------------------------------------------------- #
# 2. resolution must not pick the bogus short code
# --------------------------------------------------------------------------- #
def test_resolve_avoids_bogus_short_name():
    reset_caches()
    catalogue = {
        8: {"s8-a": "A", "erb": "facebook"},
        13: {"ikm": "instagram"},
        1: {"esb": "facebook"},
    }

    def handler(q):
        if q["action"] == "getServices":
            return json.dumps(catalogue.get(int(q["operator"]), {}))
        return "{}"

    install_fake_calls(handler)
    loop = asyncio.new_event_loop()
    try:
        pair = loop.run_until_complete(T.resolve_service("whatsapp"))
        check("whatsapp resolves to curated wqp/13", pair == ("wqp", 13), pair)
        check("whatsapp never resolves to s8-a", pair[0] != "s8-a", pair)

        fb = loop.run_until_complete(T.resolve_service("facebook"))
        check("facebook resolves to a real code",
              fb[0] in ("erb", "esb"), fb)

        cands = loop.run_until_complete(T.resolve_candidates("whatsapp"))
        check("candidates never contain s8-a",
              all(c != "s8-a" for c, _ in cands), cands)
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# 3. multi-route pricing: route 13 empty, route 4 answers
# --------------------------------------------------------------------------- #
def test_multi_route_prices():
    reset_caches()
    catalogue = {13: {"ikm": "instagram"}, 4: {"iam": "Instagram"}}

    def handler(q):
        action = q["action"]
        op = int(q.get("operator") or 0)
        if action == "getServices":
            return json.dumps(catalogue.get(op, {}))
        if action == "getCountries":
            return json.dumps(COUNTRIES) if op in (13, 4) else "{}"
        if action == "getPricesV3":
            service = q.get("service")
            cid = str(q.get("country"))
            if service == "ikm" and op == 13:
                return "BAD_SERVICE"
            if service == "iam" and op == 4:
                return json.dumps({cid: {"iam": {"price": 13.08, "count": 4}}})
            return "{}"
        return "{}"

    install_fake_calls(handler)
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(T.get_countries("instagram"))
        check("multi-route get_countries ok", res.get("ok") is True, res)
        check("multi-route picked operator 4", res.get("operator") == 4, res)
        check("multi-route picked code iam", res.get("service_code") == "iam", res)
        countries = res.get("countries") or []
        check("multi-route returned countries", bool(countries), res)
        if countries:
            check("multi-route price parsed",
                  countries[0].get("price") == 13.08, countries[0])
            check("multi-route stock parsed",
                  countries[0].get("stock") == 4, countries[0])
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# 4. genuinely empty stock is reported honestly, never blamed on the key
# --------------------------------------------------------------------------- #
def test_unavailable_is_honest():
    reset_caches()
    catalogue = {13: {"tvm": "telegram"}}

    def handler(q):
        action = q["action"]
        op = int(q.get("operator") or 0)
        if action == "getServices":
            return json.dumps(catalogue.get(op, {}))
        if action == "getCountries":
            return json.dumps(COUNTRIES) if op == 13 else "{}"
        if action == "getPricesV3":
            return "{}"  # provider recognises the code, has zero stock
        return "{}"

    install_fake_calls(handler)
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(T.get_countries("telegram"))
        check("empty stock is not ok", res.get("ok") is False, res)
        check("empty stock flagged unavailable", res.get("unavailable") is True, res)
        err = str(res.get("error") or "")
        check("error says no live numbers", "no live numbers" in err.lower(), err)
        check("error never blames the api key",
              "api-key" not in err.lower() and "api key" not in err.lower(), err)
        check("empty stock returns no countries", res.get("countries") == [], res)
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
def main():
    tests = [
        test_score_name,
        test_resolve_avoids_bogus_short_name,
        test_multi_route_prices,
        test_unavailable_is_honest,
    ]
    for fn in tests:
        print(f"- {fn.__name__}")
        fn()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        for name, ok, extra in CHECKS:
            if not ok:
                print(f"  FAILED: {name} {extra}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
