"""Regression tests for the 2026-10-29 console errors + search quality.

1. ``QueryIdInvalidError``
   Telethon's ``CallbackQuery.Event.edit()`` internally fires
   ``create_task(self.answer())``.  When the handler also calls ``answer()``,
   the duplicate hits an already-consumed query id and the fire-and-forget task
   logged::

       asyncio - ERROR - Task exception was never retrieved
       telethon.errors.rpcerrorlist.QueryIdInvalidError

   ``install_callback_safety`` must make that a silent no-op.

2. ``TemporaSMS get_countries(whatsapp) timed out``
   Prices + country names were fetched sequentially, so a ~150-request price
   sweep plus a getCountries call blew past the caller's 20s timeout.  They are
   now fetched concurrently under a hard budget, with stale-cache fallback.

3. Country search quality
   Short queries ("in", "us") used to match inside longer words
   ("k-i-n-gdom", "a-u-s-tralia").  Results must now be ranked best-first.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.button_safety import install_callback_safety
from utils.country_search import country_score, search_country_dicts
from utils import temporasms

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COUNTRIES = [
    {"code": "in", "name": "India"},
    {"code": "id", "name": "Indonesia"},
    {"code": "jp", "name": "Japan"},
    {"code": "us", "name": "United States"},
    {"code": "au", "name": "Australia"},
    {"code": "gb", "name": "United Kingdom"},
    {"code": "kr", "name": "South Korea"},
    {"code": "fi", "name": "Finland"},
    {"code": "pg", "name": "Papua New Guinea"},
    {"code": "gn", "name": "Guinea"},
]


# --------------------------------------------------------------------------- #
# 1. Callback answer safety
# --------------------------------------------------------------------------- #
def test_install_callback_safety_swallows_query_id_invalid():
    from telethon import events
    from telethon.errors import QueryIdInvalidError

    class _DummyEvent:
        async def answer(self, *a, **kw):
            raise QueryIdInvalidError(request=None)

    install_callback_safety(bot=object())
    assert getattr(events.CallbackQuery.Event, "_answer_safety_installed", False)

    # The patched method must return None instead of raising.
    result = asyncio.run(events.CallbackQuery.Event.answer(_DummyEvent()))
    assert result is None


def test_install_callback_safety_is_idempotent():
    from telethon import events

    install_callback_safety(bot=object())
    first = events.CallbackQuery.Event.answer
    install_callback_safety(bot=object())
    assert events.CallbackQuery.Event.answer is first


def test_main_installs_callback_safety():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert "install_callback_safety(bot)" in src


# --------------------------------------------------------------------------- #
# 2. TemporaSMS performance
# --------------------------------------------------------------------------- #
def test_temporasms_has_hard_budget():
    assert hasattr(temporasms, "_COUNTRIES_BUDGET")
    assert temporasms._COUNTRIES_BUDGET <= 20


def test_temporasms_fetches_prices_and_names_concurrently():
    src = open(os.path.join(REPO, "utils", "temporasms.py"), encoding="utf-8").read()
    start = src.index("async def get_countries")
    block = src[start:start + 3000]
    assert "asyncio.gather" in block
    assert "wait_for" in block
    # Sequential fetch was the bug.
    assert "prices = await _prices_for(service)" not in block


def test_temporasms_timeouts_are_short():
    assert temporasms._TIMEOUT.total <= 15
    assert temporasms._SWEEP_TIMEOUT.total <= 15


def test_prices_for_falls_back_to_stale_cache():
    src = open(os.path.join(REPO, "utils", "temporasms.py"), encoding="utf-8").read()
    assert "using stale prices" in src


# --------------------------------------------------------------------------- #
# 3. Country search quality
# --------------------------------------------------------------------------- #
def test_short_query_does_not_match_inside_words():
    names = [c["name"] for c in search_country_dicts(COUNTRIES, "us")]
    assert names == ["United States"], names

    names = [c["name"] for c in search_country_dicts(COUNTRIES, "in")]
    assert names[:2] == ["India", "Indonesia"], names


def test_exact_match_ranks_first():
    names = [c["name"] for c in search_country_dicts(COUNTRIES, "guinea")]
    assert names[0] == "Guinea", names
    assert "Papua New Guinea" in names


def test_typo_tolerance():
    assert [c["name"] for c in search_country_dicts(COUNTRIES, "jpan")] == ["Japan"]


def test_dial_code_search():
    assert [c["name"] for c in search_country_dicts(COUNTRIES, "+91")] == ["India"]


def test_alias_search():
    assert [c["name"] for c in search_country_dicts(COUNTRIES, "uk")] == [
        "United Kingdom"
    ]


def test_no_match_returns_empty():
    assert search_country_dicts(COUNTRIES, "zzzzzz") == []


def test_country_score_ordering():
    assert country_score("india", "in", "India") > country_score("india", "Indonesia")


def test_build_tag_bumped_for_search():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert "2026-10-29-fast-search-v5" in src
