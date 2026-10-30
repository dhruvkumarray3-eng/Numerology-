"""Regression test: every inline button must have BOTH a colour style and a
premium (custom) emoji icon, and premium emojis must stay enabled.

The owner asked that premium emojis stay everywhere and that the UI colour be
applied on every screen.  This test walks the AST of every plugin/utility and
fails if any ``style_btn``/``style_url`` call is missing ``style_type`` or
``icon`` -- that is exactly how a screen silently loses its colour.

Run from the repository root:

    python3 tests/test_ui_color_premium.py
"""
import ast
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "ui-test")
os.environ.setdefault("BOT_TOKEN", "123:ui-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config                                   # noqa: E402
from utils import keyboards as kb               # noqa: E402

PASS = 0
STYLE_CALLS = ("style_btn", "style_url")


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


def _iter_calls():
    for folder in ("plugins", "utils"):
        for p in sorted((ROOT / folder).rglob("*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in STYLE_CALLS):
                    yield p, node


def test_every_button_has_colour_and_icon():
    missing_style, missing_icon = [], []
    total = 0
    for path, node in _iter_calls():
        total += 1
        kw = {k.arg for k in node.keywords if k.arg}
        if len(node.args) < 3 and "style_type" not in kw:
            missing_style.append(f"{path.name}:{node.lineno}")
        if len(node.args) < 4 and "icon" not in kw:
            missing_icon.append(f"{path.name}:{node.lineno}")
    check("style calls found", total > 400, total)
    check("every button has a colour", not missing_style, missing_style[:8])
    check("every button has a premium icon", not missing_icon, missing_icon[:8])


def test_premium_emojis_enabled():
    check("USE_PREMIUM_EMOJIS is on", bool(config.USE_PREMIUM_EMOJIS))
    check("icon registry populated", len(kb.PREMIUM_ICONS) > 40,
          len(kb.PREMIUM_ICONS))
    # A known semantic key must resolve to a real custom emoji id.
    check("back icon resolves", isinstance(kb.resolve_icon("back"), int),
          kb.resolve_icon("back"))
    check("search icon resolves", isinstance(kb.resolve_icon("search"), int),
          kb.resolve_icon("search"))


def test_pe_renders_tg_emoji():
    out = kb.pe("crown", "C")
    check("pe emits tg-emoji", "<tg-emoji emoji-id=" in out, out)


def test_colour_styles_are_valid():
    valid = {"primary", "success", "danger"}
    bad = []
    for path, node in _iter_calls():
        style = None
        if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
            style = node.args[2].value
        for k in node.keywords:
            if k.arg == "style_type" and isinstance(k.value, ast.Constant):
                style = k.value.value
        if isinstance(style, str) and style not in valid:
            bad.append(f"{path.name}:{node.lineno}={style}")
    check("only primary/success/danger used", not bad, bad[:8])


def main():
    test_premium_emojis_enabled()
    test_pe_renders_tg_emoji()
    test_colour_styles_are_valid()
    test_every_button_has_colour_and_icon()
    print(f"OK {PASS} checks passed")


if __name__ == "__main__":
    main()
