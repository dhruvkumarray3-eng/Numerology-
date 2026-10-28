"""Repo-wide guarantee: EVERY Search button uses the owner's premium emoji id.

Run from the repository root:

    python3 tests/test_search_emoji_all.py

The owner asked for emoji id 5229102316145106683 on every search button in
the bot.  This test walks every plugin/util module, finds each ``style_btn``
call, folds its label to ASCII, and asserts that any label containing
"search" passes ``icon=SEARCH_EMOJI_ID`` (or the raw id).
"""
import io
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "search-emoji-test")
os.environ.setdefault("BOT_TOKEN", "123:search-emoji-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.keyboards import SEARCH_EMOJI_ID, normalise_menu_text  # noqa: E402

PASS = 0
SEARCH_ID = 5229102316145106683


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


def find_calls(src, name):
    out = []
    idx = 0
    while True:
        i = src.find(name + "(", idx)
        if i == -1:
            break
        j = i + len(name) + 1
        depth, in_str, esc = 1, None, False
        while j < len(src) and depth > 0:
            ch = src[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
            else:
                if ch in "\"'":
                    in_str = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            j += 1
        out.append((i, j))
        idx = j
    return out


def first_label(call):
    body = call[len("style_btn("):]
    m = re.match(r"\s*[fFrRbB]?([\"'])", body)
    if not m:
        return ""
    quote = m.group(1)
    start = i = m.end()
    esc = False
    while i < len(body):
        ch = body[i]
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == quote:
            return body[start:i]
        i += 1
    return ""


def main():
    check("constant value", SEARCH_EMOJI_ID == SEARCH_ID, SEARCH_EMOJI_ID)

    search_buttons = 0
    files = []
    for root in ("plugins", "utils"):
        for dirpath, _d, names in os.walk(ROOT / root):
            for n in names:
                if n.endswith(".py"):
                    files.append(Path(dirpath) / n)

    for path in files:
        src = io.open(path, encoding="utf-8").read()
        for start, end in find_calls(src, "style_btn"):
            call = src[start:end]
            label = first_label(call)
            # A button is a "search button" when its label reads "search"
            # (after folding stylised Unicode) or carries the magnifier glyph.
            is_search = ("search" in normalise_menu_text(label)) or ("\U0001F50D" in label)
            if not is_search:
                continue
            search_buttons += 1
            ok = ("SEARCH_EMOJI_ID" in call) or (str(SEARCH_ID) in call)
            check(f"{path.name}: {label[:30]!r} uses search emoji", ok, call[:120])

    check("found search buttons", search_buttons >= 25, search_buttons)

    kb = io.open(ROOT / "utils" / "keyboards.py", encoding="utf-8").read()
    check("constant defined in keyboards",
          re.search(r"^SEARCH_EMOJI_ID\s*=\s*5229102316145106683", kb, re.M) is not None)
    check("PREMIUM_ICONS search key", '"search": 5229102316145106683' in kb)

    print(f"OK: {PASS} checks passed across {search_buttons} search buttons")


if __name__ == "__main__":
    main()
