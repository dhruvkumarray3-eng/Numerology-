"""Regression tests for the rewritten TemporaSMS client.

These tests never touch the network: ``_call`` / ``_call_conn`` and the
aiohttp session are replaced with fakes that replay the exact payload shapes
the live panel returns.  Run with:

    API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_temporasms.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# --------------------------------------------------------------------------- #
# 1. error parsing
# --------------------------------------------------------------------------- #
def test_error_codes():
    check("json errorCode", T._error_code(
        '{"success": false, "errorCode": "NO_BALANCE", "message": "x"}') == "NO_BALANCE")
    check("bare token", T._error_code("NO_BALANCE") == "NO_BALANCE")
    check("bare BAD_SERVICE", T._error_code(" BAD_SERVICE ") == "BAD_SERVICE")
    check("success payload", T._error_code('{"success": true}') is None)
    check("normal text", T._error_code("ACCESS_BALANCE:1.5") is None)
    check("access cancel is not an error", T._error_code("ACCESS_CANCEL") is None)
    check("status token is not an error", T._error_code("STATUS_WAIT_CODE") is None)
    check("empty", T._error_code("") is None)

    msg = T.friendly_error("NO_BALANCE")
    check("friendly NO_BALANCE", "wallet is empty" in (msg or ""), msg)
    check("friendly NO_ACTIVATION",
          "expired" in (T.friendly_error("NO_ACTIVATION") or ""))
    check("friendly unknown", (T.friendly_error("WAT") or "").startswith("Panel error"))


# --------------------------------------------------------------------------- #
# 2. activation parsing
# --------------------------------------------------------------------------- #
def test_parse_activation():
    check("classic", T._parse_activation("ACCESS_NUMBER:12345:79001234567")
          == ("12345", "79001234567"))
    check("v2 json", T._parse_activation(
        '{"success": true, "data": {"id": 987, "phone": "+919812345678"}}')
        == ("987", "+919812345678"))
    check("flat json", T._parse_activation(
        '{"activationId": 5, "phoneNumber": "123"}') == ("5", "123"))
    check("garbage", T._parse_activation("BAD_KEY") == (None, None))


# --------------------------------------------------------------------------- #
# 3. service resolution + catalogue
# --------------------------------------------------------------------------- #
CATALOGUE_BY_OP = {
    13: {"tvm": "telegram", "wqp": "whatsapp", "gre": "Google"},
    1: {"esb": "facebook", "sjo": "Discord", "tvm": "telegram"},
    4: {"iam": "Instagram"},
    7: {"kct": "TikTok"},
}


def test_catalogue_and_resolution():
    reset_caches()
    import json

    def handler(q):
        if q["action"] == "getServices":
            return json.dumps(CATALOGUE_BY_OP.get(int(q["operator"]), {}))
        return "{}"

    install_fake_calls(handler)
    loop = asyncio.new_event_loop()

    cat = loop.run_until_complete(T._catalogue())
    check("catalogue size", len(cat) == 7, len(cat))
    check("telegram prefers op13", cat["tvm"]["operator"] == 13)
    check("tvm operators include 1", 1 in cat["tvm"]["operators"], cat["tvm"])

    check("resolve telegram", loop.run_until_complete(T.resolve_service("telegram"))
          == ("tvm", 13))
    check("resolve whatsapp", loop.run_until_complete(T.resolve_service("whatsapp"))
          == ("wqp", 13))
    check("resolve instagram", loop.run_until_complete(T.resolve_service("instagram"))
          == ("iam", 4))
    check("resolve tiktok", loop.run_until_complete(T.resolve_service("tiktok"))
          == ("kct", 7))
    check("resolve by code", loop.run_until_complete(T.resolve_service("esb"))
          == ("esb", 1))

    ops = loop.run_until_complete(T._operators_for_code("tvm"))
    check("operators_for_code prefers 13", ops[0] == 13 and 1 in ops, ops)
    loop.close()


# --------------------------------------------------------------------------- #
# 4. country id resolution ordering
# --------------------------------------------------------------------------- #
COUNTRIES = {
    "1": "Ukraine", "15": "Poland", "22": "India", "187": "United States",
    "4": "Philippines", "60": "Bangladesh", "19": "Nigeria", "31": "Indonesia",
}


def test_country_resolution():
    reset_caches()
    T._COUNTRIES_CACHE[13] = {"ts": 9e18, "data": dict(COUNTRIES)}
    loop = asyncio.new_event_loop()

    cases = {"in": "22", "India": "22", "ph": "4", "us": "187",
             "United States": "187", "ng": "19", "bd": "60", "id": "31"}
    for query, want in cases.items():
        got = loop.run_until_complete(T._resolve_country_id(query, 13))
        check(f"country {query!r} -> {want}", got == want, got)

    check("numeric passthrough",
          loop.run_until_complete(T._resolve_country_id("22", 13)) == "22")
    check("unknown country",
          loop.run_until_complete(T._resolve_country_id("atlantis", 13)) is None)
    loop.close()


# --------------------------------------------------------------------------- #
# 5. price sweep parsing
# --------------------------------------------------------------------------- #
def test_price_sweep():
    reset_caches()
    T._COUNTRIES_CACHE[13] = {"ts": 9e18, "data": dict(COUNTRIES)}

    def handler(q):
        if q["action"] == "getPricesV3":
            cid = str(q["country"])
            if cid == "22":
                return ('{"22": {"tvm": {"price": 28.359, "count": 12, '
                        '"providers": {"13": {"count": 12, "price": [28.359]}}}}}')
            if cid == "15":
                return '{"15": {"tvm": {"price": 14.5482, "count": 350000}}}'
            return "{}"
        return "{}"

    install_fake_calls(handler)
    loop = asyncio.new_event_loop()

    prices = loop.run_until_complete(T._sweep_prices("tvm", 13))
    check("sweep found 2 countries", len(prices) == 2, prices)
    check("india price", prices.get("22", {}).get("price") == 28.359, prices.get("22"))
    check("india stock", prices.get("22", {}).get("stock") == 12)
    check("poland price", prices.get("15", {}).get("price") == 14.5482)
    check("poland stock", prices.get("15", {}).get("stock") == 350000)
    loop.close()


# --------------------------------------------------------------------------- #
# 6. get_countries end-to-end
# --------------------------------------------------------------------------- #
def test_get_countries():
    reset_caches()
    import json

    def handler(q):
        action = q["action"]
        if action == "getServices":
            return json.dumps(CATALOGUE_BY_OP.get(int(q["operator"]), {}))
        if action == "getCountries":
            return json.dumps(COUNTRIES if int(q["operator"]) == 13 else {"1": "Ukraine"})
        if action == "getPricesV3":
            cid = str(q["country"])
            if cid == "22":
                return '{"22": {"tvm": {"price": 28.359, "count": 12}}}'
            if cid == "15":
                return '{"15": {"tvm": {"price": 14.5482, "count": 350000}}}'
            return "{}"
        return "{}"

    install_fake_calls(handler)
    loop = asyncio.new_event_loop()

    res = loop.run_until_complete(T.get_countries("telegram"))
    check("get_countries ok", res["ok"], res.get("error"))
    check("get_countries service_code", res.get("service_code") == "tvm")
    check("get_countries operator", res.get("operator") == 13)
    names = [c["name"] for c in res["countries"]]
    check("get_countries only priced", set(names) == {"India", "Poland"}, names)
    check("get_countries sorted cheapest first", names[0] == "Poland", names)
    check("get_countries iso codes",
          {c["code"] for c in res["countries"]} == {"in", "pl"},
          [c["code"] for c in res["countries"]])
    loop.close()


# --------------------------------------------------------------------------- #
# 7. balance parsing
# --------------------------------------------------------------------------- #
def test_balance():
    reset_caches()
    loop = asyncio.new_event_loop()

    install_fake_calls(lambda q: "ACCESS_BALANCE:0.6332")
    bal = loop.run_until_complete(T.get_balance())
    check("classic balance ok", bal["ok"])
    check("classic balance value", abs(bal["balance"] - 0.6332) < 1e-9, bal)
    check("classic balance currency", bal["currency"] == "RUB")

    install_fake_calls(lambda q: '{"balance": "12.5", "currency": "RUB"}')
    bal = loop.run_until_complete(T.get_balance())
    check("json balance", bal["ok"] and bal["balance"] == 12.5, bal)

    install_fake_calls(lambda q: "BAD_KEY")
    bal = loop.run_until_complete(T.get_balance())
    check("bad key balance", not bal["ok"] and "invalid" in (bal["error"] or "").lower(), bal)
    loop.close()


# --------------------------------------------------------------------------- #
# 8. cross-operator country fallback
# --------------------------------------------------------------------------- #
def test_cross_operator_country():
    reset_caches()
    T._CATALOGUE["data"] = {
        "tvm": {"name": "telegram", "operator": 13, "operators": [1, 13]},
    }
    T._CATALOGUE["ts"] = 9e18
    T._COUNTRIES_CACHE[13] = {"ts": 9e18, "data": {"22": "India"}}
    T._COUNTRIES_CACHE[1] = {"ts": 9e18, "data": {"187": "United States"}}

    loop = asyncio.new_event_loop()
    pid, op, code = loop.run_until_complete(
        T.resolve_country_route("telegram", "United States"))
    check("fallback to op1", (pid, op, code) == ("187", 1, "tvm"), (pid, op, code))

    pid, op, code = loop.run_until_complete(T.resolve_country_route("telegram", "India"))
    check("preferred route kept", (pid, op, code) == ("22", 13, "tvm"), (pid, op, code))

    pid, op, code = loop.run_until_complete(T.resolve_country_route("telegram", "atlantis"))
    check("unknown -> None", pid is None, (pid, op, code))
    loop.close()


# --------------------------------------------------------------------------- #
# 9. buy_number friendly errors
# --------------------------------------------------------------------------- #
def test_buy_number_errors():
    reset_caches()
    T._CATALOGUE["data"] = {
        "tvm": {"name": "telegram", "operator": 13, "operators": [13]},
    }
    T._CATALOGUE["ts"] = 9e18
    T._COUNTRIES_CACHE[13] = {"ts": 9e18, "data": {"22": "India"}}

    loop = asyncio.new_event_loop()

    install_fake_calls(lambda q: '{"success": false, "errorCode": "NO_BALANCE", '
                                 '"message": "no money"}')
    res = loop.run_until_complete(T.buy_number("telegram", "in"))
    check("buy NO_BALANCE not ok", not res["ok"])
    check("buy NO_BALANCE friendly", "wallet is empty" in res["error"], res["error"])

    install_fake_calls(lambda q: "ACCESS_NUMBER:777:919812345678")
    res = loop.run_until_complete(T.buy_number("telegram", "in"))
    check("buy success ok", res["ok"], res)
    check("buy success order", res["order_id"] == "777", res)
    check("buy success phone", res["phone"] == "919812345678", res)
    check("buy success operator", res["operator"] == 13, res)

    res = loop.run_until_complete(T.buy_number("telegram", "atlantis"))
    check("buy unknown country", not res["ok"] and "Unknown country" in res["error"], res)
    loop.close()


def main():
    tests = [
        test_error_codes, test_parse_activation, test_catalogue_and_resolution,
        test_country_resolution, test_price_sweep, test_get_countries,
        test_balance, test_cross_operator_country, test_buy_number_errors,
    ]
    for t in tests:
        print(f"\n== {t.__name__}")
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            CHECKS.append((t.__name__, False, str(exc)))

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
