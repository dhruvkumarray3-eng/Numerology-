"""Regression guard: every reply-keyboard label routes to its own screen.

Background
----------
The bottom keyboard renders labels with mathematical-bold / small-capital
Unicode glyphs (e.g. ``📊 𝐒ᴛᴏᴄᴋ``).  Handlers used to re-type those glyphs in
a regex, and a single wrong Unicode block silently broke the button:

  * ``📊 𝐒ᴛᴏᴄᴋ``  (U+1D412 bold S) was compared against ``𝕊`` (U+1D54A
    double-struck S) in one revision.
  * ``👤 𝐏ʀᴏꜰɪʟᴇ`` (U+1D40F bold P) was compared against ``ℙ`` (U+2119
    double-struck P).

When the regex missed, the tap fell through to the catch-all text handler in
``plugins/buy.py`` and was answered with "No country found matching
'📊 𝐒ᴛᴏᴄᴋ'" if a country search happened to be pending.

The fix routes on a canonical key derived by folding the glyphs, so a glyph
change can never break routing again.  These checks lock that in.
"""
import os
import pathlib
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
os.environ.setdefault("ADMIN_ID", "1")

from utils.keyboards import (  # noqa: E402
    get_persistent_menu,
    menu_label_key,
    is_menu_label,
    normalise_menu_text,
)

CHECKS = []


def check(name, cond, detail=None):
    CHECKS.append((name, bool(cond), detail))


def _labels():
    rows = get_persistent_menu(1)
    return [b.button.text for row in rows for b in row]


def _source(rel):
    return pathlib.Path(ROOT, rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Canonical folding of the real keyboard labels
# ---------------------------------------------------------------------------
labels = _labels()
expected = {
    "buyaccount": "buy_account",
    "deposit": "deposit",
    "profile": "profile",
    "myorders": "my_orders",
    "balance": "balance",
    "stock": "stock",
    "refer": "refer",
    "support": "support",
    "start": "start",
    "close": "close",
    "help": "help",
    "adminpanel": "admin_panel",
}

seen = {}
for label in labels:
    key = normalise_menu_text(label)
    seen[key] = label
    check(f"label {key!r} folds to a canonical key",
          menu_label_key(label) is not None,
          f"{label!r} -> {menu_label_key(label)!r}")

for key, canonical in expected.items():
    check(f"keyboard exposes {canonical}",
          key in seen and menu_label_key(seen[key]) == canonical,
          seen.get(key))

# ---------------------------------------------------------------------------
# 2. Exact matching: a real country query is NOT a menu label
# ---------------------------------------------------------------------------
check("'Stockholm' is not the Stock button", not is_menu_label("Stockholm"))
check("'Japan' is not a menu label", not is_menu_label("Japan"))
check("'+91' is not a menu label", not is_menu_label("+91"))
check("empty text is not a menu label", not is_menu_label(""))
check("None is not a menu label", not is_menu_label(None))

# ---------------------------------------------------------------------------
# 3. Handlers use the folding matcher, not a hardcoded glyph regex
# ---------------------------------------------------------------------------
callbacks_src = _source("plugins/callbacks.py")
profile_src = _source("plugins/profile.py")
buy_src = _source("plugins/buy.py")

check("Stock handler uses menu_label_key",
      'menu_label_key(e.raw_text) == "stock"' in callbacks_src)
check("Refer handler uses menu_label_key",
      'menu_label_key(e.raw_text) == "refer"' in callbacks_src)
check("My Orders handler uses menu_label_key",
      'menu_label_key(e.raw_text) == "my_orders"' in callbacks_src)
check("Balance handler uses menu_label_key",
      'menu_label_key(e.raw_text) == "balance"' in callbacks_src)
check("Support handler uses menu_label_key",
      'menu_label_key(e.raw_text) == "support"' in callbacks_src)
check("Profile handler uses menu_label_key",
      'menu_label_key(e.raw_text) == "profile"' in profile_src)

check("Stock handler stops propagation",
      "raise events.StopPropagation" in callbacks_src)
check("Profile handler stops propagation",
      "raise events.StopPropagation" in profile_src)

# The old hardcoded Stock/Profile glyph regexes must be gone.  These are the
# exact wrong-block glyphs that used to be typed into the handlers.
check("no double-struck Stock glyph regex remains",
      "\U0001D54A\u1d1b\u1d0f\u1d04\u1d0b" not in callbacks_src)
check("no double-struck Profile glyph regex remains",
      "\u2119\U0001D4F7\U0001D4EE\U0001D4F3\U0001D4F2\U0001D4F5\U0001D4EE" not in profile_src)

# ---------------------------------------------------------------------------
# 4. Catch-all country search ignores every menu label
# ---------------------------------------------------------------------------
check("buy catch-all guards on is_menu_label",
      "is_menu_label(event.text)" in buy_src)
check("buy catch-all clears pending search state",
      "search_state.pop(uid, None)" in buy_src)

# ---------------------------------------------------------------------------
# 5. Live handler registration: the Stock/Profile funcs accept the real label
# ---------------------------------------------------------------------------
from telethon import TelegramClient  # noqa: E402
from plugins import register_all_handlers  # noqa: E402


class _FakeBot:
    """Collect ``(event_builder, callback)`` pairs like a Telethon client."""

    def __init__(self):
        self.handlers = []

    def on(self, builder):
        def decorator(fn):
            self.handlers.append((builder, fn))
            return fn
        return decorator


def _register():
    bot = _FakeBot()
    try:
        register_all_handlers(bot)
    except Exception as exc:  # noqa: BLE001
        check("register_all_handlers completes", False, f"{type(exc).__name__}: {exc}")
        return bot
    check("register_all_handlers completes", True)
    return bot


bot = _register()
check("handlers were registered", len(bot.handlers) > 0, len(bot.handlers))


class _FakeEvent:
    is_private = True
    out = False

    def __init__(self, text):
        self.raw_text = text
        self.text = text


def _handler_for(fn_name):
    for builder, fn in bot.handlers:
        if getattr(fn, "__name__", "") == fn_name:
            return builder, fn
    return None, None


for fn_name, label_key, real_label in (
    ("msg_stock", "stock", seen.get("stock")),
    ("msg_profile", "profile", seen.get("profile")),
):
    builder, fn = _handler_for(fn_name)
    check(f"{fn_name} is registered", fn is not None)
    if fn is None:
        continue
    func = getattr(builder, "func", None)
    check(f"{fn_name} uses a func matcher (not a regex)", func is not None)
    if func is None or real_label is None:
        continue
    try:
        ok_real = bool(func(_FakeEvent(real_label)))
        ok_country = bool(func(_FakeEvent("Stockholm" if label_key == "stock" else "Japan")))
    except Exception as exc:  # noqa: BLE001
        check(f"{fn_name} matcher runs", False, f"{type(exc).__name__}: {exc}")
        continue
    check(f"{fn_name} matches its real keyboard label", ok_real, real_label)
    check(f"{fn_name} ignores a country query", not ok_country)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
failed = [c for c in CHECKS if not c[1]]
for name, ok, detail in CHECKS:
    if not ok:
        print(f"FAIL: {name}" + (f"  [{detail}]" if detail is not None else ""))
print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
if failed:
    sys.exit(1)
print("ALL MENU-LABEL ROUTING CHECKS PASSED")
