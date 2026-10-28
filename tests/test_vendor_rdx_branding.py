"""Branding test: no "VTH" left, brand is "VENDOR SELLINGS RDX", premium emojis.

Run from the repository root:

    python3 tests/test_vendor_rdx_branding.py
"""
import asyncio
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "branding-test")
os.environ.setdefault("BOT_TOKEN", "123:branding-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plugins.product_panels as pp  # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


class FakeEvent:
    def __init__(self):
        self.sender_id = 999
        self.text = None
        self.out = False

    async def edit(self, text, buttons=None):
        self.captured = (text, buttons)

    async def respond(self, text, buttons=None):
        self.captured = (text, buttons)

    async def answer(self, *a, **k):
        pass


def main():
    # 1. "VTH" must not exist anywhere in the source tree.
    offenders = []
    for dirpath, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        for n in names:
            if not n.endswith((".py", ".md", ".json", ".txt", ".html")):
                continue
            if n == Path(__file__).name:
                continue
            fp = Path(dirpath) / n
            try:
                txt = io.open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if "vth" in txt.lower():
                offenders.append(str(fp.relative_to(ROOT)))
    check("no VTH left in repo", not offenders, offenders)

    # 2. The panel hub shows the new brand.
    ev = FakeEvent()
    asyncio.run(pp.show_panel_hub(ev))
    text, btns = ev.captured
    check("brand present", "VENDOR SELLINGS RDX" in text, text[:120])
    check("activation subtitle", "SMS &amp; Virtual Number Activation" in text)

    # 3. Premium emojis are used in the hub message.
    check("premium emojis in hub", text.count("<tg-emoji emoji-id=") >= 8,
          text.count("<tg-emoji emoji-id="))

    # 4. Every hub button carries a premium icon id.
    flat = [b for row in btns for b in row]
    check("hub has 6 buttons", len(flat) == 6, len(flat))
    for b in flat:
        icon = getattr(getattr(b, "style", None), "icon", None)
        check(f"button {b.text!r} has icon", isinstance(icon, int) and icon > 0, icon)

    # 5. Help screen uses premium emojis too.
    ev = FakeEvent()
    asyncio.run(pp.show_help(ev))
    check("help premium", "<tg-emoji emoji-id=" in ev.captured[0])

    print(f"OK: {PASS} checks passed")


if __name__ == "__main__":
    main()
