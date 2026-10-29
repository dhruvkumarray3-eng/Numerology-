"""Deep audit: every button must reach a real, registered handler.

Unlike tests/test_dead_buttons.py (which only greps source text), this script
actually registers all plugins on a fake client and then evaluates each
button against Telethon's own ``EventBuilder.filter`` logic - the same code
Telegram events go through at runtime.

Checks
------
1. Every reply-keyboard label matches at least one ``NewMessage`` handler.
2. Every inline callback-data literal matches at least one ``CallbackQuery``
   handler.
3. No callback pattern is registered twice (would double-handle taps).
"""
import asyncio
import os
import pathlib
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
os.environ.setdefault("ADMIN_ID", "1")

from telethon import TelegramClient, events

from config import bot as runtime_bot
from plugins import register_all_handlers
from utils.keyboards import get_persistent_menu


class FakeEvent:
    """Just enough surface for EventBuilder.filter() to run."""

    def __init__(self, text="", data=None, private=True):
        self.raw_text = text
        self.text = text
        self.message = type("M", (), {
            "message": text, "raw_text": text, "out": False,
            "sender_id": 1, "fwd_from": None, "id": 1,
        })()
        self.data = data
        self.query = type("Q", (), {"data": data, "chat_instance": "1"})()
        self.pattern_match = None
        self.data_match = None
        self.is_private = private
        self.is_channel = False
        self.is_group = False
        self.chat_id = 1
        self.sender_id = 1
        self.out = False

    def __getattr__(self, item):
        return None


def collect_callback_literals():
    """All inline callback-data literals used as button payloads (AST-based)."""
    import ast

    found = set()
    for path in pathlib.Path(ROOT, "plugins").glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name not in ("style_btn", "inline"):
                continue
            if len(node.args) < 2:
                continue
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, (str, bytes)):
                value = arg.value
                if isinstance(value, bytes):
                    value = value.decode("utf-8", "ignore")
                found.add(value)
    return found


async def main():
    # main.py registers handlers on config.bot, and many plugins attach
    # handlers at import time via @bot.on(...) on that same instance, so the
    # audit must inspect exactly that client.
    client = runtime_bot
    summary = register_all_handlers(client)
    print("plugins:", summary)

    builders = [b for _, b in client.list_event_handlers()]
    # EventBuilder.filter() returns early until the builder is resolved
    # against a client - do that here so the checks behave like runtime.
    for b in builders:
        if not getattr(b, "resolved", True):
            try:
                await b.resolve(client)
            except Exception:
                pass

    msg_builders = [b for b in builders if isinstance(b, events.NewMessage)]
    cb_builders = [b for b in builders if isinstance(b, events.CallbackQuery)]

    # ---- 1. reply keyboard labels -------------------------------------
    built = client.build_reply_markup(get_persistent_menu(1))
    labels = [btn.text for row in built.rows for btn in row.buttons]

    print(f"\n-- reply keyboard ({len(labels)} labels) --")
    dead = []
    for label in labels:
        ev = FakeEvent(text=label)
        hit = False
        for b in msg_builders:
            try:
                if b.filter(ev):
                    hit = True
                    break
            except Exception as ex:
                print("   !! filter error on", getattr(b, "pattern", None), "->", ex)
        print(("  OK   " if hit else "  DEAD ") + label)
        if not hit:
            dead.append(label)

    # ---- 2. inline callback literals ----------------------------------
    literals = sorted(collect_callback_literals())
    print(f"\n-- inline callbacks ({len(literals)} literals) --")
    dead_cb = []
    for data in literals:
        ev = FakeEvent(data=data.encode())
        hit = False
        for b in cb_builders:
            try:
                if b.filter(ev):
                    hit = True
                    break
            except Exception as ex:
                print("   !! cb filter error on", getattr(b, "pattern", None), "->", ex)
        if not hit:
            dead_cb.append(data)

    if dead_cb:
        for d in dead_cb:
            print("  DEAD " + d)
    else:
        print("  all callback literals reach a handler")

    # ---- 3. duplicate callback patterns -------------------------------
    seen, dupes = {}, []
    for b in cb_builders:
        pat = getattr(b, "pattern", None)
        if pat is None:
            continue
        key = pat.pattern if hasattr(pat, "pattern") else pat
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            dupes.append(key)
    print(f"\n-- duplicate callback patterns: {len(dupes)} --")
    for d in dupes:
        print("  DUP", d)

    print("\nRESULT:", "FAIL" if (dead or dead_cb or dupes) else "ALL CLEAN")
    return 1 if (dead or dead_cb or dupes) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
