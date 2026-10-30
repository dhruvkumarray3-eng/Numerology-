"""Regression tests for provider base-URL normalisation and search quality.

Two real-world failures are pinned here:

1. A wrong base URL saved in the admin panel (``https://api.grabmail.io/v1``
   for Temp Mail, ``https://temporasms.com/api`` for TemporaSMS) used to 404
   on every call, which surfaced as "Temp Mail test failed: 404" and
   "Status: Not configured" even though the API key was valid.  The clients
   now normalise any stored value onto the one real endpoint.

2. App / country search now tolerates typos, abbreviations, multi-word
   queries and filler words ("india number", "chat gpt", "telegrm").

Run either way:
    python3 tests/test_provider_url_and_search.py
    pytest tests/test_provider_url_and_search.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")

from utils import tempmail as tm          # noqa: E402
from utils import temporasms as ts        # noqa: E402
from utils import country_search as cs   # noqa: E402
import plugins.all_apps as aa             # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL {label} {detail}"
    PASS += 1


# ---------------------------------------------------------------------------
# 1. Temp Mail base URL normalisation
# ---------------------------------------------------------------------------
def test_tempmail_base_normalisation():
    canon = "https://grabmail.io/api/v1"
    for bad in (
        "https://api.grabmail.io/v1",
        "https://api.grabmail.io/v1/messages",
        "https://grabmail.io",
        "https://www.grabmail.io",
        "https://grabmail.io/api",
        "",
    ):
        check(f"tempmail {bad!r} -> canonical", tm._normalise_base(bad) == canon,
              tm._normalise_base(bad))
    check("tempmail already-canonical stays", tm._normalise_base(canon) == canon)
    check("tempmail custom host gains /api/v1",
          tm._normalise_base("https://myhost.com") == "https://myhost.com/api/v1")


# ---------------------------------------------------------------------------
# 2. TemporaSMS base URL normalisation
# ---------------------------------------------------------------------------
def test_temporasms_base_normalisation():
    canon = "https://api.temporasms.com"
    for bad in (
        "https://temporasms.com/api",
        "https://temporasms.com",
        "https://api.temporasms.com/stubs/handler_api.php",
        "https://api.temporasms.com/stubs",
        "",
    ):
        check(f"temporasms {bad!r} -> canonical", ts._normalise_base(bad) == canon,
              ts._normalise_base(bad))
    check("temporasms already-canonical stays", ts._normalise_base(canon) == canon)


# ---------------------------------------------------------------------------
# 3. App search
# ---------------------------------------------------------------------------
def test_app_search_quality():
    def top(q):
        r = aa._search_apps(q)
        return r[0][1].lower() if r else ""

    check("typo telegrm -> telegram", "telegram" in top("telegrm"))
    check("abbrev tg -> telegram", "telegram" in top("tg"))
    check("multiword chat gpt -> openai", "openai" in top("chat gpt"))
    check("hyphen whats-app -> whatsapp", "whatsapp" in top("whats-app"))
    check("multiword google mail -> google", "google" in top("google mail"))
    check("abbrev insta -> instagram", "instagram" in top("insta"))
    check("abbrev fb -> facebook", "facebook" in top("fb"))
    check("garbage returns nothing", aa._search_apps("zzzzqqq") == [])


# ---------------------------------------------------------------------------
# 4. Country search
# ---------------------------------------------------------------------------
def test_country_search_quality():
    check("filler 'india number' matches India",
          cs.country_score("india number", "India") > 0)
    check("filler 'buy usa sim' matches United States",
          cs.country_score("buy usa sim", "United States") > 0)
    check("token-set 'south korea' matches",
          cs.country_score("south korea", "South Korea") >= 60)
    check("typo 'germny' matches Germany",
          cs.country_score("germny", "Germany") > 0)
    check("dial '+91' matches India", cs.country_score("+91", "India") >= 90)
    check("resolve 'india number'",
          (cs.resolve_country("india number") or {}).get("name") == "India")
    check("resolve 'buy usa sim'",
          (cs.resolve_country("buy usa sim") or {}).get("name") == "United States")


if __name__ == "__main__":
    for fn in (test_tempmail_base_normalisation, test_temporasms_base_normalisation,
               test_app_search_quality, test_country_search_quality):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\nALL {PASS} CHECKS PASSED")
