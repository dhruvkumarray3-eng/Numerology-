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


# Telegram hard limits
MEDIA_CAPTION_LIMIT = 1024
TEXT_MESSAGE_LIMIT = 4096


def install_edit_safety(bot, event_cls=None):
    """Wrap ``CallbackQuery.Event.edit`` so caption-length errors cannot crash.

    The "join our channels" screen is a **photo**.  Telegram caps media
    captions at 1024 characters, but the Terms & Conditions text is ~2.5k
    characters.  ``await event.edit(terms_message, ...)`` therefore raised::

        telethon.errors.rpcerrorlist.MediaCaptionTooLongError

    which escaped the handler (only ``MessageNotModifiedError`` was caught),
    leaving the user stuck on the join screen forever.

    This process-wide guard turns that failure into a graceful recovery:
    delete the un-editable media message and send the text as a fresh
    plain-text message (4096-char budget), truncating only if it is still too
    long.  Individual call sites can no longer reintroduce this bug.

    Idempotent: calling it twice will not double-wrap.
    """
    from telethon import events
    from telethon.errors import (
        MessageNotModifiedError,
        MediaCaptionTooLongError,
        MessageTooLongError,
    )

    Event = event_cls or events.CallbackQuery.Event
    if getattr(Event, "_edit_safety_installed", False):
        return bot

    original = Event.edit

    async def safe_edit(self, *args, **kwargs):
        try:
            return await original(self, *args, **kwargs)
        except MessageNotModifiedError:
            # Preserve the original contract: callers may catch this.
            raise
        except (MediaCaptionTooLongError, MessageTooLongError) as exc:
            text = kwargs.get("text", kwargs.get("message"))
            if text is None and args:
                text = args[0]
            if text is None:
                logger.error(f"\u26a0\ufe0f edit failed with no text to resend: {exc}")
                return None

            logger.warning(
                "\u26a0\ufe0f %s on a media message; resending as plain text "
                "(the photo caption limit is %d chars).",
                type(exc).__name__, MEDIA_CAPTION_LIMIT,
            )

            buttons = kwargs.get("buttons")
            parse_mode = kwargs.get("parse_mode", "html")
            if isinstance(text, str) and len(text) > TEXT_MESSAGE_LIMIT:
                text = text[: TEXT_MESSAGE_LIMIT - 20] + "\n\n\u2026 (truncated)"

            try:
                await self.delete()
            except Exception:
                pass

            try:
                return await self.client.send_message(
                    self.chat_id, text, buttons=buttons, parse_mode=parse_mode
                )
            except Exception as send_exc:  # noqa: BLE001
                logger.error(
                    "\u26a0\ufe0f resend after caption error failed (%s); "
                    "retrying without buttons.", send_exc,
                )
                try:
                    return await self.client.send_message(
                        self.chat_id, text, parse_mode=parse_mode
                    )
                except Exception as final_exc:  # noqa: BLE001
                    logger.error(f"\u26a0\ufe0f resend failed entirely: {final_exc}")
                    return None

    Event.edit = safe_edit
    Event._edit_safety_installed = True
    logger.info(
        "\u2705 Edit safety net installed (media-caption overflow auto-recovers)."
    )
    return bot
