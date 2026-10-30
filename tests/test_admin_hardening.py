"""Regression tests for the admin hardening pass.

Covers three real bugs found during the full-repo audit:

1. ``utils.imap_verifier.get_imap_credentials`` used to fall back to a
   hard-coded Gmail address + app password.  This repository is public, so
   that was a credential leak.  Credentials must come from the settings
   table (or IMAP_USER / IMAP_PASS) and default to empty.
2. ``run_stock_check`` crashed with ``AttributeError: 'NoneType' object has
   no attribute 'edit'`` when the progress message could not be posted.
3. ``admin_actions`` had a catch-all ``^adm_`` pattern that opened a
   10-minute ``bot.conversation`` for *any* unrecognised ``adm_*`` payload,
   silently swallowing everything the admin typed.  Unknown payloads must
   now be answered with a friendly "re-open the panel" screen instead.

Run from the repository root:

    python3 tests/test_admin_hardening.py
"""
import asyncio
import inspect
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "admin-hardening")
os.environ.setdefault("BOT_TOKEN", "123:admin-hardening")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


# ---------------------------------------------------------------------------
# 1. no hard-coded IMAP credentials
# ---------------------------------------------------------------------------
def test_no_hardcoded_imap_credentials():
    src = (ROOT / "utils" / "imap_verifier.py").read_text(encoding="utf-8")
    # A bare "@gmail.com" is fine (it is the Gmail *domain* constant used to
    # force imap.gmail.com); a full hard-coded address is not.
    check("no gmail address baked in",
          not re.search(r"[A-Za-z0-9._%+\-]+@gmail\.com", src))
    check("no app password baked in", "dqwo agxp" not in src)
    check("reads IMAP_USER env", "IMAP_USER" in src)
    check("reads IMAP_PASS env", "IMAP_PASS" in src)

    from utils.imap_verifier import get_imap_credentials
    from database import cur, db

    cur.execute("DELETE FROM settings WHERE key IN ('gmail_user','gmail_pass')")
    db.commit()
    user, pwd = get_imap_credentials()
    check("unconfigured returns empty user", user == "", repr(user))
    check("unconfigured returns empty password", pwd == "", repr(pwd))

    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_user', ?)",
                ("owner@example.com",))
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_pass', ?)",
                ("app-pass",))
    db.commit()
    user, pwd = get_imap_credentials()
    check("configured user is returned", user == "owner@example.com", user)
    check("configured password is returned", pwd == "app-pass", pwd)
    cur.execute("DELETE FROM settings WHERE key IN ('gmail_user','gmail_pass')")
    db.commit()


# ---------------------------------------------------------------------------
# 2. run_stock_check survives a failed progress message
# ---------------------------------------------------------------------------
class _DeadEvent:
    """respond() raises - the progress message can never be created."""

    sender_id = 1
    chat_id = 1

    async def respond(self, *a, **kw):
        raise ConnectionError("offline")


class _SilentMsg:
    async def edit(self, *a, **kw):
        raise ConnectionError("offline")


class _HalfDeadEvent:
    sender_id = 1
    chat_id = 1

    async def respond(self, *a, **kw):
        return _SilentMsg()


def test_stock_check_survives_failed_messages():
    from plugins import admin_actions as aa
    from database import cur, db

    # empty stock table -> the "no stock" branch must not raise
    cur.execute("UPDATE stock SET available=0")
    db.commit()

    asyncio.run(aa.run_stock_check(_DeadEvent()))
    check("run_stock_check survives respond() failure", True)

    asyncio.run(aa.run_stock_check(_HalfDeadEvent()))
    check("run_stock_check survives edit() failure", True)

    src = inspect.getsource(aa.run_stock_check)
    check("progress edits go through _say", "_say(" in src)


# ---------------------------------------------------------------------------
# 3. unknown adm_* payloads never open a conversation
# ---------------------------------------------------------------------------
class _Event:
    def __init__(self, data):
        self.data = data.encode()
        self.sender_id = 1
        self.chat_id = 1
        self.id = 1
        self.client = None
        self.raw_text = ""
        self.text = ""
        self.pattern_match = None
        self.edited = None
        self.answers = []

    async def edit(self, text, buttons=None, **kw):
        self.edited = (text, buttons)

    async def respond(self, text, buttons=None, **kw):
        self.edited = (text, buttons)

    async def reply(self, text, buttons=None, **kw):
        self.edited = (text, buttons)

    async def answer(self, *a, **kw):
        self.answers.append((a, kw))

    async def delete(self, *a, **kw):
        return None

    async def get_reply_message(self):
        return None


def test_unknown_admin_payload_is_safe():
    from plugins import admin_actions as aa

    for payload in ("adm_bogus", "adm_stale_button|x", "adm_zzz|1|2"):
        ev = _Event(payload)
        asyncio.run(asyncio.wait_for(aa.admin_actions(ev), timeout=5))
        check(f"{payload} is answered", bool(ev.answers), payload)
        check(f"{payload} renders a screen", bool(ev.edited), payload)
        text = ev.edited[0]
        check(f"{payload} explains the problem", "Unknown action" in text, text[:80])

    src = inspect.getsource(aa.admin_actions)
    check("wizard allow-list exists", "_WIZARDS" in src)
    check("unknown payloads bail out before the 600s conversation",
          src.index("if not _is_wizard:")
          < src.index("async with bot.conversation(chat, timeout=600)"))
    for name in ("addstock", "addzip", "bcast", "ban", "restoreusr",
                 "setlztkey", "change_upi", "change_gmail", "add_fsub"):
        check(f"wizard {name} allow-listed", f'"{name}"' in src, name)


# ---------------------------------------------------------------------------
# 4. admin dashboard "back" path has a working edit()
# ---------------------------------------------------------------------------
def test_dashboard_shim_has_edit():
    from plugins import admin_actions as aa

    src = inspect.getsource(aa.admin_actions)
    check("dashboard shim defines edit()",
          "async def edit(self, text, buttons=None" in src)
    check("dashboard shim uses send_message", "bot.send_message(chat, text" in src)


def main():
    test_no_hardcoded_imap_credentials()
    test_stock_check_survives_failed_messages()
    test_unknown_admin_payload_is_safe()
    test_dashboard_shim_has_edit()
    print(f"OK - {PASS} checks passed")


if __name__ == "__main__":
    main()
