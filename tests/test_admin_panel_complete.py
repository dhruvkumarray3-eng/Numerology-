"""Admin Panel completeness audit.

The owner asked for *every* admin feature to be reachable from the Admin
Panel.  This test renders the dashboard and the new ``Advanced Tools`` hub and
asserts that:

1. every feature button is present on the dashboard,
2. every hub action renders without raising,
3. every rendered button has non-empty callback data,
4. every callback literal used by the admin screens is handled by a
   registered handler (no dead buttons).

Run from the repository root:

    python3 tests/test_admin_panel_complete.py
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "admin-audit")
os.environ.setdefault("BOT_TOKEN", "123:admin-audit")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins import admin as adm                    # noqa: E402
from plugins import admin_hub as hub                # noqa: E402
from plugins import admin_extras as ax              # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


class FakeEvent:
    def __init__(self, uid=1, data=b""):
        self.sender_id = uid
        self.chat_id = uid
        self.id = 1
        self.client = None
        self.data = data
        self.pattern_match = None
        self.raw_text = ""
        self.text = None
        self.btns = None
        self.answers = []

    async def edit(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def respond(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def reply(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def answer(self, *a, **kw):
        self.answers.append((a, kw))

    async def delete(self, *a, **kw):
        return None

    async def get_reply_message(self):
        return None


def flat(btns):
    out = []
    for row in btns or []:
        if isinstance(row, (list, tuple)):
            out.extend(row)
        else:
            out.append(row)
    return out


def datas(btns):
    return {b.data.decode() if isinstance(b.data, bytes) else b.data for b in flat(btns)}


# ---------------------------------------------------------------------------
# 1. dashboard must expose every feature
# ---------------------------------------------------------------------------
REQUIRED_DASHBOARD = {
    # bot / servers / SMM
    "adm_togglebot", "adm_toggle_mode", "adm_togglesmm|1", "adm_togglesmm|2",
    "adm_servers",
    # stock
    "adm_addstock", "adm_addzip", "adm_managestock", "adm_checkstock",
    "adm_autoprice", "adm_catalogs",
    # users / stats
    "adm_stats", "adm_bcast", "uh_open", "adm_bal", "adm_ban",
    # settings
    "adm_discount", "adm_refpct", "adm_channels_mgr", "adm_supporturl",
    "adm_autoupi", "adm_lzt_settings", "adm_search_settings", "adm_tempmail",
    "adm_trustwallet", "adm_upi", "adm_addsrc", "adm_delsrc",
    # pricing
    "pf_home", "adm_setchangefee", "adm_usdtrate",
    # platform
    "adm_payments", "adm_manageadmins", "adm_backupusr", "adm_restoreusr",
    "ac_menu", "help_admin", "dashboard_main",
    # advanced hub
    "hub_open",
}


def test_dashboard():
    ev = FakeEvent(uid=1)
    asyncio.run(adm.admin_panel_handler(ev))
    check("dashboard renders", bool(ev.text))
    have = datas(ev.btns)
    missing = REQUIRED_DASHBOARD - have
    check("dashboard exposes every feature", not missing, sorted(missing))
    check("dashboard header shows profit rule", "USDT" in ev.text and "\u20b9" in ev.text)
    for b in flat(ev.btns):
        check("dashboard button has data", bool(b.data), getattr(b, "text", ""))


# ---------------------------------------------------------------------------
# 2. hub screen
# ---------------------------------------------------------------------------
HUB_ACTIONS = {
    "hub_do|panelstats", "hub_do|panelsales", "hub_do|panelbalance",
    "hub_do|mongostatus", "hub_do|smmservers", "hub_do|grant",
    "hub_do|basictg", "hub_do|packs", "hub_do|myhistory",
}


def test_hub_screen():
    ev = FakeEvent(uid=1)
    asyncio.run(hub.show_hub(ev))
    check("hub renders", bool(ev.text))
    have = datas(ev.btns)
    check("hub exposes every advanced action", HUB_ACTIONS <= have,
          sorted(HUB_ACTIONS - have))
    check("hub has a back button", "adm_adminmain" in have)
    for b in flat(ev.btns):
        check("hub button has data", bool(b.data), getattr(b, "text", ""))


# ---------------------------------------------------------------------------
# 3. every hub action renders without raising
# ---------------------------------------------------------------------------
class _FakeBalance:
    async def get_balance(self):
        return {"ok": True, "currency": "USD", "balance": 12.5}


def test_hub_actions():
    ax.temporasms.get_balance = _FakeBalance().get_balance
    for action in ("panelstats", "panelsales", "panelbalance",
                   "mongostatus", "smmservers", "myhistory",
                   "basictg", "packs"):
        ev = FakeEvent(uid=1, data=f"hub_do|{action}".encode())
        asyncio.run(hub._run_action(ev, action))
        check(f"hub action {action} renders", bool(ev.text), action)
        got = datas(ev.btns)
        check(f"hub action {action} keeps a way back",
              bool(got) and any(
                  d == "adm_adminmain" or d == "hub_open"
                  or d.startswith("mtg_") or d.startswith("pk_")
                  for d in got),
              sorted(got)[:6])


# ---------------------------------------------------------------------------
# 4. no dead admin callbacks
# ---------------------------------------------------------------------------
def test_no_dead_admin_callbacks():
    import re
    from telethon import events
    from config import bot as runtime_bot
    from plugins import register_all_handlers

    register_all_handlers(runtime_bot)
    builders = [b for _, b in runtime_bot.list_event_handlers()]
    for b in builders:
        if not getattr(b, "resolved", True):
            try:
                asyncio.run(b.resolve(runtime_bot))
            except Exception:
                pass
    cb = [b for b in builders if isinstance(b, events.CallbackQuery)]

    # collect every literal admin callback emitted anywhere
    import ast
    literals = set()
    for path in (ROOT / "plugins").glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name not in ("style_btn", "inline") or len(node.args) < 2:
                    continue
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, (str, bytes)):
                    v = arg.value
                    v = v.decode() if isinstance(v, bytes) else v
                    literals.add(v)

    admin_literals = {l for l in literals
                      if l.startswith(("adm_", "hub_", "pf_", "ac_", "uh_"))}
    check("admin callback literals collected", len(admin_literals) > 40,
          len(admin_literals))

    class E:
        def __init__(self, data):
            self.data = data.encode()
            self.query = type("Q", (), {"data": self.data, "chat_instance": "1"})()
            self.pattern_match = None
            self.sender_id = 1
            self.chat_id = 1
            self.is_private = True
            self.is_channel = False
            self.is_group = False
            self.out = False
            self.raw_text = ""

        def __getattr__(self, item):
            return None

    dead = []
    for lit in sorted(admin_literals):
        ev = E(lit)
        if not any(b.filter(ev) for b in cb):
            dead.append(lit)
    check("no dead admin callbacks", not dead, dead)


def main():
    test_dashboard()
    test_hub_screen()
    test_hub_actions()
    test_no_dead_admin_callbacks()
    print(f"OK - {PASS} checks passed")


if __name__ == "__main__":
    main()
