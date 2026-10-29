"""Tests for the admin User History console (plugins/user_history.py).

Covers:
  * data collection on an empty / unknown user
  * rendering of every tab (overview, deposits, purchases, wallet, timeline)
  * pagination maths
  * premium-emoji + colour-button usage
  * handler registration (all uh_* callbacks + the id-input router)
  * the admin panel button now opens the console

Run from the repository root:

    python3 tests/test_user_history.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "uh-test")
os.environ.setdefault("BOT_TOKEN", "123:uh-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins import user_history as uh          # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


class FakeEvent:
    def __init__(self, uid=1):
        self.sender_id = uid
        self.text = None
        self.btns = None
        self.answers = []
        self.replies = []

    async def edit(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def respond(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def reply(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons
        self.replies.append(text)

    async def answer(self, *a, **k):
        self.answers.append(a)


class RecBot:
    """Minimal Telethon bot stub that records registered patterns."""

    def __init__(self):
        self.patterns = []

    def on(self, ev=None, **kw):
        def deco(fn):
            match = getattr(ev, "match", None)
            if match is None:
                match = getattr(ev, "pattern", None)
            pattern = getattr(match, "__self__", match)
            self.patterns.append(pattern)
            return fn
        return deco


def all_buttons(btns):
    for row in btns or []:
        for b in row:
            yield b


def button_data(b):
    d = getattr(b, "data", b"")
    return d.decode() if isinstance(d, bytes) else str(d)


def button_icon(b):
    st = getattr(b, "style", None)
    return getattr(st, "icon", None) if st is not None else None


def button_bg(b):
    st = getattr(b, "style", None)
    if st is None:
        return None
    return (getattr(st, "bg_primary", None) or getattr(st, "bg_success", None)
            or getattr(st, "bg_danger", None))


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. data collection on an unknown user
# ---------------------------------------------------------------------------
d = uh.collect_user_history(999999999)
check("unknown user flagged", d["exists"] is False)
for key in ("balance", "total_deposited", "deposits", "purchases", "wallet",
            "timeline", "deposit_total", "purchase_total", "profit_total",
            "deposit_count", "purchase_count"):
    check(f"collect has {key}", key in d)
check("empty timeline", d["timeline"] == [])

# ---------------------------------------------------------------------------
# 2. every tab renders text + colour buttons with icons
# ---------------------------------------------------------------------------
for tab in uh.TAB_KEYS:
    text, btns = uh.render_tab(d, tab)
    check(f"tab {tab} text", isinstance(text, str) and len(text) > 20)
    check(f"tab {tab} buttons", bool(btns))
    # premium emoji present in message text
    check(f"tab {tab} premium emoji", "<tg-emoji" in text, text[:80])
    for b in all_buttons(btns):
        check(f"tab {tab} button icon {button_data(b)}", button_icon(b) is not None)
        check(f"tab {tab} button colour {button_data(b)}", button_bg(b) is not None)

# every tab button points at a registered uh_ callback
tab_data = {button_data(b) for b in all_buttons(uh.render_tab(d, "overview")[1])}
check("refresh button", any(x.startswith("uh_home|") for x in tab_data))
check("another user button", "uh_open" in tab_data)
check("change balance button", any(x.startswith("uh_bal|") for x in tab_data))
check("toggle ban button", any(x.startswith("uh_ban|") for x in tab_data))
check("admin panel button", "adm_adminmain" in tab_data)

# ---------------------------------------------------------------------------
# 3. pagination maths
# ---------------------------------------------------------------------------
items = [{"icon": "\U0001F4B3", "label": f"item {i}", "amount": i, "status": "success",
          "date": 0, "ref": i} for i in range(20)]
body, page, pages, total = uh._page(items, 1)
check("page size", total == 20 and pages == 4 and page == 1)
check("page 1 items", body.count("\n\n") == uh.PAGE_SIZE - 1)
body2, page2, _, _ = uh._page(items, 4)
check("last page clamp", page2 == 4)
body3, page3, _, _ = uh._page(items, 99)
check("page clamp high", page3 == 4)

# ---------------------------------------------------------------------------
# 4. status badges + tier ladder
# ---------------------------------------------------------------------------
check("badge success", uh._status_badge("success").startswith("\u2705"))
check("badge pending", uh._status_badge("pending").startswith("\u23f3"))
check("badge failed", uh._status_badge("failed").startswith("\u274c"))
check("tier bronze", uh._tier(0)[0] == "Bronze")
check("tier silver", uh._tier(500)[0] == "Silver")
check("tier gold", uh._tier(2500)[0] == "Gold")
check("tier diamond no next", uh._tier(20000) == ("Diamond", 0))
check("timestamp int", uh._ts(1761600000) == 1761600000.0)
check("timestamp iso", uh._ts("2025-10-27 21:20:00") > 0)
check("timestamp empty", uh._ts(None) == 0.0)

# ---------------------------------------------------------------------------
# 5. show_user no-data path
# ---------------------------------------------------------------------------
ev = FakeEvent()
run(uh.show_user(ev, 999999999, "overview"))
check("no-data message", ev.text and "No data found" in ev.text)
check("no-data buttons", bool(ev.btns))

# ---------------------------------------------------------------------------
# 6. handler registration
# ---------------------------------------------------------------------------
bot = RecBot()
uh.register_user_history(bot)
sources = [p.pattern.decode() if isinstance(p.pattern, bytes) else p.pattern
           for p in bot.patterns if p is not None]
joined = " ".join(sources)
for needle in ("uh_open", "uh_cancel", "uh_home", "uh_tab", "uh_pg", "uh_bal", "uh_ban"):
    check(f"handler {needle}", needle in joined)
check("command handler", "userhistory" in joined)
check("9 handlers registered", len(bot.patterns) == 9, len(bot.patterns))

# ---------------------------------------------------------------------------
# 7. admin panel button rewired to the console
# ---------------------------------------------------------------------------
admin_src = (ROOT / "plugins" / "admin.py").read_text(encoding="utf-8")
check("admin button opens console", '"uh_open"' in admin_src)
check("admin button no longer adm_userinfo",
      'style_btn("User Info", "adm_userinfo"' not in admin_src)

# ---------------------------------------------------------------------------
# 8. module wired into the bot
# ---------------------------------------------------------------------------
init_src = (ROOT / "plugins" / "__init__.py").read_text(encoding="utf-8")
check("module imported", "from plugins.user_history import register_user_history" in init_src)
check("module registered",
      '("user_history", register_user_history)' in init_src
      or "register_user_history(bot)" in init_src)

# legacy adm_userinfo delegates to the console
actions_src = (ROOT / "plugins" / "admin_actions.py").read_text(encoding="utf-8")
check("legacy userinfo delegates", "from plugins.user_history import show_user" in actions_src)

print(f"{PASS}/{PASS} checks passed")
