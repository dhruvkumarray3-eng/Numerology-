"""Regression tests for the LIVE All Apps OTP search (``search_services``).

The All Apps OTP hub now asks the panel itself which services exist instead of
only matching a hard-coded local list.  That introduced a nasty scoring bug:
a service literally named "A" (code ``s8-a``) matched every query because
``"a"`` is a substring of everything, and Chinese names ending in "APP"
matched nonsense queries like ``zzzznotanapp``.

Rules locked in here:

1. A one-character service name never matches a long query.
2. A nonsense query returns zero hits (no garbage).
3. Real queries return the right app first (``chat gpt`` -> ChatGPT).
4. Results are capped by ``limit`` and carry slug/name/operator/score.
5. A dead panel returns ``ok=False`` with an error, never an exception.

Run with:

    API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_live_app_search.py
"""
import asyncio
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
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# A miniature stand-in for the real panel catalogue.  It deliberately includes
# the pathological entries that broke the old scorer.
FAKE_CATALOGUE = {
    "s8-a": {"name": "A", "operator": 8},
    "s10-avtodortr": {"name": "\u0410\u0432\u0442\u043e\u0434\u043e\u0440", "operator": 10},
    "zp-fp": {"name": "\u522b\u6837APP", "operator": 13},
    "iam": {"name": "Instagram", "operator": 13},
    "cht": {"name": "ChatGPT", "operator": 13},
    "pjko": {"name": "ChatGPT | OpenAI", "operator": 13},
    "kct": {"name": "TikTok", "operator": 13},
    "ffk": {"name": "Facebook", "operator": 13},
    "gil": {"name": "Gmail", "operator": 13},
    "ddd": {"name": "Discord", "operator": 13},
}


async def _fake_catalogue():
    return dict(FAKE_CATALOGUE)


async def _dead_catalogue():
    raise RuntimeError("panel down")


def run(query, limit=20):
    return asyncio.run(T.search_services(query, limit=limit))


def main():
    original = T._catalogue

    T._catalogue = _fake_catalogue
    try:
        r = run("telegram")
        check("telegram: ok", r["ok"])
        check("telegram: no one-letter 'A' match",
              all(h["slug"] != "s8-a" for h in r["services"]),
              str(r["services"]))

        r = run("whatsapp")
        check("whatsapp: no one-letter 'A' match",
              all(h["slug"] != "s8-a" for h in r["services"]),
              str(r["services"]))
        check("whatsapp: no 'APP' suffix garbage",
              all("app" not in h["name"].lower() for h in r["services"]),
              str(r["services"]))

        r = run("zzzznotanapp")
        check("nonsense query: zero hits", r["services"] == [], str(r["services"]))

        r = run("chat gpt")
        check("chat gpt: ChatGPT ranked first",
              r["services"] and r["services"][0]["slug"] == "cht",
              str(r["services"][:3]))

        r = run("tik tok")
        check("tik tok: TikTok ranked first",
              r["services"] and r["services"][0]["slug"] == "kct",
              str(r["services"][:3]))

        r = run("instagram")
        check("instagram: exact match score 100",
              r["services"] and r["services"][0]["slug"] == "iam"
              and r["services"][0]["score"] == 100,
              str(r["services"][:3]))

        r = run("facebook", limit=2)
        check("limit respected", len(r["services"]) <= 2, str(len(r["services"])))

        r = run("discord")
        hit = r["services"][0] if r["services"] else {}
        check("hit shape has slug/name/operator/score",
              {"slug", "name", "operator", "score"} <= set(hit.keys()),
              str(hit))

        r = run("")
        check("empty query: no hits, ok", r["ok"] and r["services"] == [])
    finally:
        T._catalogue = original

    T._catalogue = _dead_catalogue
    try:
        r = run("instagram")
        check("dead panel: ok=False", r["ok"] is False)
        check("dead panel: error text present", bool(r["error"]), str(r))
        check("dead panel: no services", r["services"] == [])
    finally:
        T._catalogue = original

    failed = [c for c in CHECKS if not c[1]]
    print(f"\nPASSED: {len(CHECKS) - len(failed)}  FAILED: {len(failed)}  TOTAL: {len(CHECKS)}")
    sys.exit(1 if failed else 0)


main()
