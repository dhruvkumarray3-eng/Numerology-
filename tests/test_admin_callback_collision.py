"""Regression test: the admin catch-all must not swallow panel buttons.

BUG (before the fix)
--------------------
``plugins/admin_actions.py`` registers a catch-all::

    @bot.on(events.CallbackQuery(pattern=r"^adm_"))

Telethon dispatches an update to *every* matching handler, so pressing
``adm_tempmail`` (owned by ``plugins/admin.py``) first rendered the correct
Temp Mail panel and then the catch-all overwrote it with::

    "This button belongs to an older version of the panel."

That is the exact error the owner saw in the screenshot.  The fix is an
ownership guard in ``utils/admin_routing.py``: the catch-all returns
immediately for payloads another plugin owns.

The guard lives in its own Telethon-free module precisely so this test can
run without booting the bot or touching the database.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.admin_routing import OWNED_ELSEWHERE, is_owned_elsewhere

OWNED = [
    b"adm_tempmail",
    b"adm_tm_test",
    b"adm_tm_provider",
    b"adm_tm_toggle",
    b"adm_tm_website",
    b"adm_tm_key",
    b"adm_tm_base",
    b"adm_tm_domain",
    b"adm_tm_reset",
    b"adm_tm_refresh",
    b"adm_otp",
    b"adm_otp_key",
    b"adm_otp_base",
    b"adm_otp_test",
    b"adm_otp_reset",
    b"adm_catalogs",
    b"adm_catalog_manage|panel",
    b"adm_catalog_toggle|panel|3",
    b"adm_catalog_stock|source|7",
]


def test_owned_payloads_are_skipped():
    for payload in OWNED:
        assert is_owned_elsewhere(payload), f"{payload!r} would hit the catch-all"
        # str form must behave identically (some call sites pass text).
        assert is_owned_elsewhere(payload.decode())


def test_unknown_payloads_still_reach_the_catch_all():
    for payload in (b"adm_something_unknown", b"adm_togglebot", b"adm_discount",
                    b"adm_setchangefee", b"", None):
        assert not is_owned_elsewhere(payload), f"{payload!r} was wrongly skipped"


def test_guard_covers_every_owned_screen():
    """If a new admin screen is added, its prefix must be in the guard."""
    for prefix in ("adm_tempmail", "adm_tm_", "adm_otp", "adm_catalogs", "adm_catalog_"):
        assert prefix in OWNED_ELSEWHERE


if __name__ == "__main__":
    test_owned_payloads_are_skipped()
    test_unknown_payloads_still_reach_the_catch_all()
    test_guard_covers_every_owned_screen()
    print("PASS admin callback collision")
