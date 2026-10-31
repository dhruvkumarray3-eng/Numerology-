"""Regression guard for the bottom reply keyboard (persistent menu).

Background
----------
Commit ``c8c98c2`` ("remove start sticker") deleted ``send_start_sticker_or_menu``
from ``plugins/start.py``.  That helper was the only place that sent
``get_persistent_menu(uid)`` on ``/start``, so the whole bottom reply keyboard
- including the admin/super-admin-only "Admin Panel" button - silently
disappeared from the chat.  ``/menu`` still worked, which is why nobody
noticed in code review.

These checks make sure the keyboard:
  * is a real ``ReplyKeyboardMarkup`` (not an inline keyboard),
  * is a 2-column grid (the "4 buttons in a rectangle" layout),
  * exposes every shortcut that has a text handler,
  * shows "Admin Panel" only to admins,
  * is installed on a fresh dashboard render but NOT on callback re-renders.
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

from telethon import TelegramClient
from telethon.tl.types import ReplyKeyboardMarkup

from utils.keyboards import get_persistent_menu, matches_menu

CHECKS = []


def check(name, cond, detail=None):
    CHECKS.append((name, bool(cond), detail))


def _client():
    return TelegramClient(None, 1, "x")


def _labels(markup):
    return [b.text for row in markup.rows for b in row.buttons]


# ---------------------------------------------------------------------------
# 1. Shape of the markup
# ---------------------------------------------------------------------------
markup = _client().build_reply_markup(get_persistent_menu(1))
check("persistent menu is a ReplyKeyboardMarkup",
      isinstance(markup, ReplyKeyboardMarkup), type(markup).__name__)
check("persistent menu is resized (compact)", getattr(markup, "resize", False) is True)

rows = [[b.text for b in row.buttons] for row in markup.rows]
check("persistent menu has at least 6 rows", len(rows) >= 6, len(rows))
check("first row is a 2-button grid (Buy | Deposit)",
      len(rows[0]) == 2
      and matches_menu(rows[0][0], "buy account")
      and matches_menu(rows[0][1], "deposit"), rows[0])
check("Help row is full width",
      len(rows[-2]) == 1 and matches_menu(rows[-2][0], "help"), rows[-2])

# ---------------------------------------------------------------------------
# 2. Every shortcut must have a text handler somewhere in plugins/
# ---------------------------------------------------------------------------
plugin_src = "\n".join(
    p.read_text(encoding="utf-8", errors="ignore")
    for p in pathlib.Path(ROOT, "plugins").glob("*.py")
)

REQUIRED = ["buy account", "deposit", "profile", "my orders", "balance",
            "stock", "refer", "support", "start", "close", "help"]
labels = _labels(markup)
for label in REQUIRED:
    check(f"keyboard exposes '{label}'",
          any(matches_menu(t, label) for t in labels), labels)

check("'buy account' is matched via matches_menu()",
      'matches_menu(e.raw_text, "buy account")' in plugin_src)
# Handlers must route on the canonical folded key (or, for the few that still
# use a literal regex, mention the plain label).  This replaced the old
# "handler regex mentions '<label>'" check, which broke as soon as the
# glyph-mismatched Stock/Profile regexes were replaced by folding matchers.
CANONICAL_LABELS = {
    "Deposit": "deposit", "Profile": "profile", "My Orders": "my_orders",
    "Balance": "balance", "Stock": "stock", "Refer": "refer",
    "Support": "support", "Admin Panel": "admin_panel",
}
for literal, key in CANONICAL_LABELS.items():
    check(f"handler routes '{literal}'",
          f'menu_label_key(e.raw_text) == "{key}"' in plugin_src
          or literal in plugin_src)

# ---------------------------------------------------------------------------
# 3. Admin-only button
# ---------------------------------------------------------------------------
admin_labels = _labels(_client().build_reply_markup(get_persistent_menu(1)))
check("admin sees the Admin Panel button",
      any(matches_menu(t, "admin panel") for t in admin_labels), admin_labels)

non_admin_labels = _labels(_client().build_reply_markup(get_persistent_menu(987654321)))
check("non-admin does NOT see the Admin Panel button",
      not any(matches_menu(t, "admin panel") for t in non_admin_labels), non_admin_labels)

# ---------------------------------------------------------------------------
# 4. send_main_menu installs it on fresh renders only
# ---------------------------------------------------------------------------
start_src = pathlib.Path(ROOT, "plugins", "start.py").read_text(encoding="utf-8")
check("install_persistent_menu() helper exists",
      "async def install_persistent_menu(" in start_src)
check("send_main_menu calls install_persistent_menu()",
      "await install_persistent_menu(bot, event, uid)" in start_src)
check("install is skipped for callback re-renders",
      "if not isinstance(event, events.CallbackQuery.Event):" in start_src)

# The install must be silent (no "menu ready" sentence), but the carrier
# message itself must NOT be deleted: Telegram drops a reply keyboard as soon
# as the message that installed it is deleted, which made the menu flash in
# and then vanish.
check("install uses a tiny carrier text",
      '_MENU_CARRIER_TEXT = "\\u2328\\ufe0f"' in start_src)
check("install does NOT delete the carrier message",
      "carrier.delete()" not in start_src)
check("no visible 'menu ready' notice is sent",
      "use the buttons below the message box" not in start_src)
check("install does not leave a visible caption",
      "\u2328\ufe0f <b>" not in start_src)
check("install is skipped when already installed",
      "if not force and (uid in _menu_installed or is_menu_installed(uid)):" in start_src)
check("install remembers the keyboard per user in the DB",
      "set_menu_installed(uid, 1)" in start_src)
check("close handler forgets the install",
      "_menu_installed.discard(e.sender_id)" in start_src)

# The keyboard must stay collapsible so the user can hide it while typing.
kb_src = pathlib.Path(ROOT, "utils", "keyboards.py").read_text(encoding="utf-8")
check("reply keyboard is not pinned persistent",
      "persistent=True" not in kb_src)
check("reply keyboard is resized", "resize=True" in kb_src)

# ---------------------------------------------------------------------------
# 5. Dashboard buttons restored from the 28 Oct menu
# ---------------------------------------------------------------------------
for cb in ("all_apps_menu", "src_code_menu", "panels_menu",
           "open_buy_categories", "mtg_home", "pp_open|whatsapp",
           "pp_open|allotp", "smm_menu_main", "servers_menu",
           "more_content", "tm_home", "open_deposit_menu",
           "profile_stats", "settings_menu", "help_main"):
    check(f"dashboard has '{cb}'", cb in start_src)

check("Buy Source Codes is no longer hidden behind a DB check",
      'if get_source_codes():' not in start_src)
check("Buy Panels is no longer hidden behind a DB check",
      'if get_panels():' not in start_src)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
failed = [c for c in CHECKS if not c[1]]
for name, ok, detail in CHECKS:
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail!r}"))
print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
if failed:
    sys.exit(1)
