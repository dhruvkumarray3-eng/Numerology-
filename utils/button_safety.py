"""Global button-structure safety net.

Telethon's ``TelegramClient.build_reply_markup`` expects a *list of rows*, i.e.
every element of the outer list must itself be an iterable of buttons:

    [[btn_a, btn_b], [btn_c]]

If any caller ever passes a flat list ``[btn_a, btn_b]`` (which is very easy to
do with a stray ``*()`` splat or an ``extend()`` on the wrong list), Telethon
raises::

    TypeError: 'KeyboardButtonCallback' object is not iterable

and the whole handler dies *before* the message is sent.  That is exactly how
the main menu stopped appearing after the terms-accept flow.

Fixing individual call sites is fragile: one new panel can reintroduce the bug.
This module installs a single, process-wide guard by wrapping
``bot.build_reply_markup`` so that **any** malformed structure is silently
repaired instead of raising.  The bot can therefore never lose a menu because
of a button-shape mistake again.
"""

import logging

logger = logging.getLogger(__name__)


def normalise_buttons(buttons):
    """Coerce any button structure into the list-of-rows shape Telethon needs.

    None                  -> None
    []                    -> None
    [btn, btn]            -> [[btn], [btn]]
    [[btn, btn], [btn]]   -> unchanged
    [btn, [btn, btn]]     -> [[btn], [btn, btn]]
    """
    if not buttons:
        return None

    rows = []
    for item in buttons:
        if item is None:
            continue
        if isinstance(item, (list, tuple)):
            row = [b for b in item if b is not None]
            if row:
                rows.append(row)
        else:
            rows.append([item])
    return rows or None


def install_button_safety(bot):
    """Wrap ``bot.build_reply_markup`` so bad button shapes can never raise.

    Idempotent: calling it twice will not double-wrap.
    """
    if getattr(bot, "_button_safety_installed", False):
        return bot

    original = bot.build_reply_markup

    def safe_build_reply_markup(buttons=None, *args, **kwargs):
        # Detect (and report) a malformed structure before repairing it.
        try:
            malformed = bool(buttons) and any(
                not isinstance(row, (list, tuple)) for row in buttons
            )
        except TypeError:
            malformed = True
        if malformed:
            logger.warning(
                "\u26a0\ufe0f Repaired a flat button list before sending "
                "(a caller passed a bare button instead of a row)."
            )

        fixed = normalise_buttons(buttons)
        try:
            return original(fixed, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - never let markup kill a handler
            logger.error(
                "\u26a0\ufe0f build_reply_markup failed even after repair (%s); "
                "sending without a keyboard.", exc,
            )
            return None

    bot.build_reply_markup = safe_build_reply_markup
    bot._button_safety_installed = True
    logger.info("\u2705 Button safety net installed (flat button lists auto-repaired).")
    return bot
