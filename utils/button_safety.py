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


def sanitize_text(text):
    """Remove lone UTF-16 surrogates that crash ``.encode('utf-8')``.

    A literal ``"\\ud83d\\udcac"`` in source is *two* lone surrogates, not the
    emoji U+1F4AC.  Telethon then dies with::

        UnicodeEncodeError: 'utf-8' codec can't encode characters in
        position 2-3: surrogates not allowed

    ``encode('utf-8', 'ignore')`` drops the unpaired code units while leaving
    every valid character (including real astral emoji) untouched.
    """
    if not isinstance(text, str):
        return text
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", "ignore").decode("utf-8", "ignore")


def sanitize_buttons(buttons):
    """Sanitize the visible text of every button in a normalised structure."""
    if not buttons:
        return buttons
    for row in buttons:
        if not isinstance(row, (list, tuple)):
            row = [row]
        for btn in row:
            label = getattr(btn, "text", None)
            if isinstance(label, str):
                try:
                    btn.text = sanitize_text(label)
                except Exception:
                    pass
    return buttons


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

    async def _resend_plain(self, text, buttons, parse_mode, reason):
        """Delete the media message and deliver the text as a normal message."""
        if text is None:
            logger.error(f"\u26a0\ufe0f edit failed with no text to resend: {reason}")
            return None

        logger.info(
            "\u2139\ufe0f %s on a media message; resending as plain text "
            "(the media caption limit is %d chars).",
            reason, MEDIA_CAPTION_LIMIT,
        )

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
            logger.info(
                "\u2139\ufe0f resend after caption overflow failed (%s); "
                "retrying without buttons.", send_exc,
            )
            try:
                return await self.client.send_message(
                    self.chat_id, text, parse_mode=parse_mode
                )
            except Exception as final_exc:  # noqa: BLE001
                logger.error(f"\u26a0\ufe0f resend failed entirely: {final_exc}")
                return None

    async def safe_edit(self, *args, **kwargs):
        text = kwargs.get("text", kwargs.get("message"))
        if text is None and args:
            text = args[0]

        # Proactive guard: Telegram caps media captions at 1024 chars.  If the
        # message being edited carries media and the new text is longer, the
        # edit is guaranteed to fail, so go straight to delete + resend instead
        # of logging a MediaCaptionTooLongError on every single render.
        try:
            _msg = getattr(self, "message", None)
            if (_msg is not None and getattr(_msg, "media", None)
                    and isinstance(text, str) and len(text) > MEDIA_CAPTION_LIMIT):
                return await _resend_plain(
                    self, text, kwargs.get("buttons"),
                    kwargs.get("parse_mode", "html"), "media caption limit",
                )
        except Exception:
            pass

        try:
            return await original(self, *args, **kwargs)
        except MessageNotModifiedError:
            # Preserve the original contract: callers may catch this.
            raise
        except UnicodeEncodeError:
            # Lone surrogates in the text or in a button label.  Strip them
            # and retry once so the panel still renders instead of dying.
            new_args = tuple(sanitize_text(a) for a in args)
            for key in ("text", "message", "caption"):
                if key in kwargs:
                    kwargs[key] = sanitize_text(kwargs[key])
            if kwargs.get("buttons"):
                kwargs["buttons"] = sanitize_buttons(
                    normalise_buttons(kwargs["buttons"])
                )
            try:
                return await original(self, *new_args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"\u26a0\ufe0f retry after unicode error failed: {exc}")
                return None
        except (MediaCaptionTooLongError, MessageTooLongError) as exc:
            return await _resend_plain(
                self, text, kwargs.get("buttons"),
                kwargs.get("parse_mode", "html"), type(exc).__name__,
            )

    Event.edit = safe_edit
    Event._edit_safety_installed = True
    logger.info(
        "\u2705 Edit safety net installed (media-caption overflow auto-recovers)."
    )
    return bot


def install_callback_safety(bot):
    """Wrap ``CallbackQuery.Event.answer`` so a stale query can never log an error.

    Telethon's ``CallbackQuery.Event.edit()`` internally does::

        self._client.loop.create_task(self.answer())

    If a handler *also* calls ``await event.answer(...)`` (very common: show an
    alert, then edit the message), the second answer hits Telegram with an
    already-consumed query id and raises::

        telethon.errors.rpcerrorlist.QueryIdInvalidError:
            The query ID is invalid (caused by SetBotCallbackAnswerRequest)

    Because the auto-created task is fire-and-forget, that exception surfaced as
    ``asyncio - ERROR - Task exception was never retrieved`` in the console even
    though the bot kept working.  Wrapping ``answer`` makes the duplicate a
    silent no-op, which is exactly the intended behaviour.

    Idempotent: calling it twice will not double-wrap.
    """
    from telethon import events

    Event = events.CallbackQuery.Event
    if getattr(Event, "_answer_safety_installed", False):
        return bot

    original = Event.answer

    async def safe_answer(self, *args, **kwargs):
        try:
            return await original(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - answering is best-effort
            name = type(exc).__name__
            if name in ("QueryIdInvalidError", "MessageNotModifiedError"):
                logger.debug("\u2139\ufe0f callback answer skipped (%s)", name)
            else:
                logger.debug("\u2139\ufe0f callback answer failed (%s: %s)", name, exc)
            return None

    Event.answer = safe_answer
    Event._answer_safety_installed = True
    logger.info(
        "\u2705 Callback safety net installed (duplicate/stale answers ignored)."
    )
    return bot


def install_text_safety(bot):
    """Sanitize every outgoing message/caption/button label at the client edge.

    ``safe_edit`` covers callback edits, but plain ``respond``/``send_message``
    and ``send_file`` captions bypass it.  Wrapping the three client methods
    guarantees a lone surrogate can never reach Telegram from *any* code path.

    Idempotent: calling it twice will not double-wrap.
    """
    if getattr(bot, "_text_safety_installed", False):
        return bot

    def _clean_args(args):
        return tuple(sanitize_text(a) for a in args)

    def _clean_kwargs(kwargs):
        for key in ("text", "message", "caption"):
            if key in kwargs:
                kwargs[key] = sanitize_text(kwargs[key])
        if kwargs.get("buttons"):
            kwargs["buttons"] = sanitize_buttons(
                normalise_buttons(kwargs["buttons"])
            )
        return kwargs

    for name in ("send_message", "edit_message", "send_file"):
        original = getattr(bot, name, None)
        if original is None or getattr(original, "_text_safe", False):
            continue

        def _make(orig):
            async def _wrapped(*args, **kwargs):
                return await orig(*_clean_args(args), **_clean_kwargs(kwargs))
            _wrapped._text_safe = True
            return _wrapped

        setattr(bot, name, _make(original))

    bot._text_safety_installed = True
    logger.info("\u2705 Text safety net installed (lone surrogates stripped).")
    return bot
