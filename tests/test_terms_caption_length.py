"""Regression tests for the MediaCaptionTooLongError crash.

Bug (2026-10-29):
    The "join our channels" screen is a PHOTO message.  Telegram caps media
    captions at 1024 characters, but the Terms & Conditions text is ~2.5k.
    ``cb_verify_join`` did::

        await e.edit(terms_message, buttons=get_terms_buttons())

    which raised ``MediaCaptionTooLongError``.  Only ``MessageNotModifiedError``
    was caught, so the handler died and the user never reached the Terms
    buttons or the main menu.

These tests lock in the fix:
    * the Terms text really is longer than the media caption limit;
    * ``safe_edit_or_resend`` recovers from a caption-too-long error;
    * the global ``install_edit_safety`` net recovers too;
    * ``cb_verify_join`` uses the safe helper instead of a bare edit.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon.errors import MediaCaptionTooLongError, MessageNotModifiedError

from utils.terms import get_terms_message
from utils.helpers import safe_edit_or_resend
from utils.button_safety import (
    install_edit_safety,
    MEDIA_CAPTION_LIMIT,
    TEXT_MESSAGE_LIMIT,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_terms_text_exceeds_media_caption_limit():
    """This is the actual trigger: >1024 chars but <4096 (plain text is fine)."""
    text = get_terms_message()
    assert text is not None
    assert len(text) > MEDIA_CAPTION_LIMIT, (
        "If this ever becomes short the bug is moot, but today it is long."
    )
    assert len(text) <= TEXT_MESSAGE_LIMIT


class _FakeEvent:
    """Minimal stand-in for a Telethon CallbackQuery.Event."""

    def __init__(self, edit_error=None):
        self.chat_id = 12345
        self.sender_id = 12345
        self.deleted = False
        self.edits = []
        self.sent = []
        self.client = self
        self._edit_error = edit_error

    async def edit(self, text=None, buttons=None, parse_mode="html", **kw):
        self.edits.append((text, buttons))
        if self._edit_error is not None:
            raise self._edit_error
        return "edited"

    async def delete(self):
        self.deleted = True

    async def send_message(self, chat_id, text, buttons=None, parse_mode="html", **kw):
        self.sent.append((chat_id, text, buttons))
        return "sent"


def test_safe_edit_or_resend_recovers_from_caption_too_long():
    ev = _FakeEvent(edit_error=MediaCaptionTooLongError(request=None))
    ok = asyncio.run(
        safe_edit_or_resend(ev, get_terms_message(), buttons=[[object()]])
    )
    assert ok is True
    assert ev.deleted is True, "the un-editable photo must be removed"
    assert len(ev.sent) == 1, "terms must be resent as a plain text message"
    assert ev.sent[0][1] == get_terms_message()


def test_safe_edit_or_resend_swallows_message_not_modified():
    ev = _FakeEvent(edit_error=MessageNotModifiedError(request=None))
    ok = asyncio.run(safe_edit_or_resend(ev, "same text"))
    assert ok is True
    assert ev.sent == [], "no resend needed when nothing changed"


def test_safe_edit_or_resend_normal_success_does_not_resend():
    ev = _FakeEvent()
    ok = asyncio.run(safe_edit_or_resend(ev, "hello", buttons=[[object()]]))
    assert ok is True
    assert ev.sent == []
    assert ev.edits


def test_install_edit_safety_recovers_globally():
    """The global net must turn a caption overflow into a resend."""

    class _DummyEvent:
        async def edit(self, text=None, buttons=None, parse_mode="html", **kw):
            raise MediaCaptionTooLongError(request=None)

    install_edit_safety(bot=object(), event_cls=_DummyEvent)
    assert getattr(_DummyEvent, "_edit_safety_installed", False) is True

    ev = _FakeEvent(edit_error=MediaCaptionTooLongError(request=None))
    # Call the patched method with the fake event as ``self``.
    result = asyncio.run(
        _DummyEvent.edit(ev, get_terms_message(), buttons=[[object()]])
    )
    assert result == "sent"
    assert ev.deleted is True
    assert len(ev.sent) == 1


def test_cb_verify_join_uses_safe_helper():
    src = open(os.path.join(REPO, "plugins", "callbacks.py"), encoding="utf-8").read()
    start = src.index("async def cb_verify_join")
    end = src.index("# \u2500\u2500 Keyboard Button Handlers", start)
    block = src[start:end]

    assert "safe_edit_or_resend" in block
    # The old, crash-prone pattern must be gone.
    assert "await e.edit(terms_message" not in block
    assert "await e.edit(msg, buttons=buttons)" not in block


def test_main_installs_edit_safety():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert "install_edit_safety(bot)" in src


def test_build_tag_bumped():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert "2026-10-29-terms-caption-v4" in src
