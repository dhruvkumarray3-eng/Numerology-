"""Tests for the SMM service search feature.

Run from the repository root:

    python3 tests/test_smm_search.py

Locks in the behaviour the owner asked for:

  1. ``search_smm_services`` matches any service by name / category / id.
  2. Multi-token queries require every token to be present.
  3. ``platform`` scoping filters to a single platform.
  4. Ranking puts name-prefix matches first.
  5. Every generated Search button carries the premium emoji id
     5229102316145106683 (owner-supplied).
"""
import asyncio
import io
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "smm-search-test")
os.environ.setdefault("BOT_TOKEN", "123:smm-search-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import utils.smm_client as smm  # noqa: E402

PASS = 0
SEARCH_EMOJI_ID = 5229102316145106683

CATALOGUE = [
    {"service": "101", "name": "YouTube Views Fast", "category": "YouTube Views", "rate": "0.50", "min": 100, "max": 100000},
    {"service": "102", "name": "YouTube Subscribers", "category": "YouTube Subscribers", "rate": "1.20", "min": 50, "max": 50000},
    {"service": "103", "name": "Instagram Followers HQ", "category": "Instagram Followers", "rate": "0.80", "min": 100, "max": 200000},
    {"service": "104", "name": "Instagram Likes", "category": "Instagram Likes", "rate": "0.30", "min": 10, "max": 100000},
    {"service": "105", "name": "Telegram Members", "category": "Telegram Members", "rate": "0.90", "min": 100, "max": 100000},
    {"service": "106", "name": "TikTok Likes", "category": "TikTok Likes", "rate": "0.40", "min": 50, "max": 100000},
    {"service": "107", "name": "YouTube Likes", "category": "YouTube Likes", "rate": "0.60", "min": 50, "max": 100000},
]


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


async def _fake_fetch(server=1, force_refresh=False):
    return list(CATALOGUE)


def run():
    # Patch the catalogue fetch so the search runs against a fixed dataset.
    smm.fetch_smm_services = _fake_fetch

    # 1. Basic name search.
    res = asyncio.run(smm.search_smm_services("youtube", 1))
    check("youtube matches", len(res) == 3, len(res))
    check("youtube only", all("youtube" in r["name"].lower() or "youtube" in r["category"].lower() for r in res))

    # 2. Case-insensitive.
    res_upper = asyncio.run(smm.search_smm_services("YOUTUBE", 1))
    check("case-insensitive", len(res_upper) == 3, len(res_upper))

    # 3. Multi-token query.
    res_multi = asyncio.run(smm.search_smm_services("youtube views", 1))
    check("multi-token", len(res_multi) == 1 and res_multi[0]["service"] == "101", [r["service"] for r in res_multi])

    # 4. Platform scoping.
    res_ig = asyncio.run(smm.search_smm_services("followers", 1, platform="Instagram"))
    check("platform scoping", len(res_ig) == 1 and res_ig[0]["service"] == "103", [r["service"] for r in res_ig])

    # 5. Search by exact numeric service id.
    res_id = asyncio.run(smm.search_smm_services("105", 1))
    check("service id match", any(r["service"] == "105" for r in res_id), [r["service"] for r in res_id])

    # 6. Ranking: name-prefix match first.
    res_rank = asyncio.run(smm.search_smm_services("youtube likes", 1))
    check("ranking prefix", res_rank and res_rank[0]["service"] == "107", [r["service"] for r in res_rank])

    # 7. Empty / too-short query returns nothing.
    check("empty query", asyncio.run(smm.search_smm_services("", 1)) == [])
    check("blank query", asyncio.run(smm.search_smm_services("   ", 1)) == [])

    # 8. No match.
    check("no match", asyncio.run(smm.search_smm_services("zzzznope", 1)) == [])

    # 8a. Shorthand aliases: "yt" -> youtube, "ig" -> instagram.
    res_yt = asyncio.run(smm.search_smm_services("yt views", 1))
    check("alias yt->youtube", any(r["service"] == "101" for r in res_yt), [r["service"] for r in res_yt])
    res_ig2 = asyncio.run(smm.search_smm_services("ig likes", 1))
    check("alias ig->instagram", any(r["service"] == "104" for r in res_ig2), [r["service"] for r in res_ig2])

    # 8b. Punctuation / accent normalisation.
    res_punct = asyncio.run(smm.search_smm_services("YouTube-Views!", 1))
    check("punctuation normalised", any(r["service"] == "101" for r in res_punct), [r["service"] for r in res_punct])

    # 8c. Typo tolerance (fuzzy): "youtub" should still find YouTube services.
    res_typo = asyncio.run(smm.search_smm_services("youtub", 1))
    check("typo tolerance", len(res_typo) >= 1, [r["service"] for r in res_typo])

    # 8d. Relaxed fallback: a query where one token is absent still returns
    #     results from the tokens that do match.
    res_relax = asyncio.run(smm.search_smm_services("youtube nonsenseword", 1))
    check("relaxed fallback", len(res_relax) >= 1, [r["service"] for r in res_relax])

    # 9. Every Search button in plugins/smm.py carries the premium emoji id.
    src = io.open(ROOT / "plugins" / "smm.py", encoding="utf-8").read()
    search_btn_lines = [ln for ln in src.splitlines() if "smm_search|" in ln and "style_btn" in ln]
    check("search buttons exist", len(search_btn_lines) >= 5, len(search_btn_lines))
    for ln in search_btn_lines:
        check("search button uses emoji id", "SEARCH_EMOJI_ID" in ln or str(SEARCH_EMOJI_ID) in ln, ln.strip())

    # 10. The emoji id constant is exactly the owner-supplied id.
    m = re.search(r"SEARCH_EMOJI_ID\s*=\s*(\d+)", src)
    check("emoji id constant", m and int(m.group(1)) == SEARCH_EMOJI_ID, m.group(1) if m else None)

    # 11. Callback + text router registered.
    check("callback registered", "cb_smm_search" in src)
    check("text router registered", "msg_smm_search_query" in src)
    check("stop propagation", "raise events.StopPropagation" in src)

    print(f"OK: {PASS} checks passed")


if __name__ == "__main__":
    run()
