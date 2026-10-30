"""Regression tests for the main-menu crash after Terms acceptance.

Production traceback:

    File "/home/container/utils/helpers.py", line 290, in send_preview_on_top
        markup = bot.build_reply_markup(buttons) if buttons else None
    TypeError: 'KeyboardButtonCallback' object is not iterable

Cause: ``send_main_menu`` built its keyboard with

    buttons.extend([
        ...
        *([style_btn("Free Temp Mail", ...)] if _temp_mail_visible() else []),
    ])

The ``*()`` splat unpacked a *flat* list of buttons, so a bare
``KeyboardButtonCallback`` landed in ``buttons`` instead of a row.  Telethon's
``build_reply_markup`` does ``for button in row`` and therefore blew up, which
meant the main menu was never delivered after the channel-join / terms flow.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.helpers import normalise_buttons


class _Btn:
    """Stand-in for telethon.tl.custom.Button."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<Btn {self.name}>"


def test_none_stays_none():
    assert normalise_buttons(None) is None
    assert normalise_buttons([]) is None


def test_flat_list_is_wrapped_into_rows():
    a, b = _Btn("a"), _Btn("b")
    assert normalise_buttons([a, b]) == [[a], [b]]


def test_correct_rows_are_preserved():
    a, b, c = _Btn("a"), _Btn("b"), _Btn("c")
    rows = [[a, b], [c]]
    assert normalise_buttons(rows) == [[a, b], [c]]


def test_mixed_structure_is_repaired():
    a, b, c = _Btn("a"), _Btn("b"), _Btn("c")
    assert normalise_buttons([a, [b, c]]) == [[a], [b, c]]


def test_every_row_is_iterable_after_normalisation():
    """This is the invariant Telethon's build_reply_markup relies on."""
    flat = [_Btn(str(i)) for i in range(12)]
    fixed = normalise_buttons(flat)
    assert fixed is not None
    for row in fixed:
        assert isinstance(row, (list, tuple)), f"row is not iterable: {row!r}"
        for button in row:
            assert button is not None


def test_start_menu_has_no_flat_button_splat():
    """Guard against re-introducing ``*([style_btn(...)] if ... else [])``."""
    path = os.path.join(ROOT, "plugins", "start.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()

    # A splat inside buttons.extend/append must unpack *rows*, i.e. ``*([[``.
    bad = re.findall(r"\*\(\[style_(?:btn|url)\(", src)
    assert not bad, (
        "plugins/start.py contains a flat button splat "
        "`*([style_btn(...)] ...)` — it must be `*([[style_btn(...)]] ...)` "
        "so a row (list) is inserted, not a bare button."
    )


def test_send_preview_on_top_normalises_before_building_markup():
    path = os.path.join(ROOT, "utils", "helpers.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()

    body = src.split("async def send_preview_on_top", 1)[1]
    assert "buttons = normalise_buttons(buttons)" in body, (
        "send_preview_on_top must normalise the button structure before "
        "calling bot.build_reply_markup()."
    )
    # The markup must be built only after normalisation.
    assert body.index("buttons = normalise_buttons(buttons)") < body.index(
        "bot.build_reply_markup(buttons)"
    )


def test_send_preview_on_top_has_buttonless_last_resort():
    """The menu text must still be delivered if the keyboard is rejected."""
    path = os.path.join(ROOT, "utils", "helpers.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()

    body = src.split("async def send_preview_on_top", 1)[1]
    assert "retrying without buttons" in body
    assert "return await bot.send_message(peer, message, parse_mode='html', link_preview=True)" in body


# ---------------------------------------------------------------------------
# Global safety net (utils/button_safety.py)
# ---------------------------------------------------------------------------

def test_button_safety_normalise_matches_helpers():
    from utils.button_safety import normalise_buttons as ns
    a, b = _Btn("a"), _Btn("b")
    assert ns(None) is None
    assert ns([a, b]) == [[a], [b]]
    assert ns([[a, b]]) == [[a, b]]


def test_button_safety_patches_real_telethon_client():
    """A flat list must be repaired instead of raising TypeError."""
    import os as _os
    _os.environ.setdefault("BOT_TOKEN", "1:AAFake")
    _os.environ.setdefault("API_ID", "1")
    _os.environ.setdefault("API_HASH", "0" * 32)
    _os.environ.setdefault("ADMIN_ID", "1")

    from telethon import TelegramClient, Button
    from utils.button_safety import install_button_safety

    bot = TelegramClient(":memory:", 1, "0" * 32)
    install_button_safety(bot)

    flat = [Button.inline("A", b"a"), Button.inline("B", b"b")]
    markup = bot.build_reply_markup(flat)
    assert markup is not None
    assert len(markup.rows) == 2
    assert all(len(r.buttons) == 1 for r in markup.rows)

    proper = [[Button.inline("A", b"a"), Button.inline("B", b"b")]]
    m2 = bot.build_reply_markup(proper)
    assert len(m2.rows) == 1 and len(m2.rows[0].buttons) == 2


def test_button_safety_is_idempotent():
    from telethon import TelegramClient
    from utils.button_safety import install_button_safety

    bot = TelegramClient(":memory:", 1, "0" * 32)
    install_button_safety(bot)
    first = bot.build_reply_markup
    install_button_safety(bot)
    assert bot.build_reply_markup is first


def test_button_safety_installed_at_startup():
    path = os.path.join(ROOT, "main.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "install_button_safety" in src, (
        "main.py must install the button safety net at startup."
    )
