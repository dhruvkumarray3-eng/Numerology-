"""Callback-payload ownership for the admin panel.

WHY THIS EXISTS
---------------
``plugins/admin_actions.py`` used to register a single catch-all handler::

    @bot.on(events.CallbackQuery(pattern=r"^adm_"))

Telethon does **not** stop at the first matching handler -- every matching
handler runs.  So a button owned by another plugin (``adm_tempmail``,
``adm_otp``, ``adm_catalogs`` ...) rendered its real panel and was then
overwritten by the catch-all's fallback message::

    "This button belongs to an older version of the panel."

That is the bug the owner reported.  The catch-all now asks this module
whether the payload belongs to somebody else and returns early if it does.

Kept free of Telethon/database imports on purpose so it can be unit-tested
without booting the bot.
"""
from __future__ import annotations

# Payload prefixes handled by plugins/admin.py, plugins/admin_catalogs.py and
# the other admin screens.  A prefix (not an exact match) is used so that
# parameterised payloads such as ``adm_tm_setprov|grabmail`` are covered too.
OWNED_ELSEWHERE = (
    "adm_tempmail",   # Temp Mail settings screen
    "adm_tm_",        # every Temp Mail button (key/base/domain/provider/test/...)
    "adm_otp",        # OTP / SMS (TemporaSMS) screen and its buttons
    "adm_catalogs",   # product catalogs screen
    "adm_catalog_",   # catalog manage/toggle/stock/add/... buttons
)


def is_owned_elsewhere(data) -> bool:
    """True when ``data`` (bytes or str) belongs to another admin plugin."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    if not data:
        return False
    return str(data).startswith(OWNED_ELSEWHERE)
