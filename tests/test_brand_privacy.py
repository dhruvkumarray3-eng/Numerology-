"""Regression test: provider brand names must never appear in user-facing text.

The panels are private, so nothing may mention the upstream providers by name.
Every user-visible string must simply say "Panel".

This walks the AST of ``plugins/`` (the display layer), skips docstrings, and
fails if any string literal still contains a provider brand.

Run from the repository root:

    python3 tests/test_brand_privacy.py
"""
import ast
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "brand-test")
os.environ.setdefault("BOT_TOKEN", "123:brand-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = 0

BRANDS = ("temporasms", "lzt", "lolz.live", "lolz")

# Functional values that must stay verbatim (real URLs / env var names).
ALLOWED = (
    "https://lolz.live/payment/method",
    "TEMPORASMS_API_KEY",
    "TEMPORASMS_BASE_URL",
    "/lztmargin",
    "/setlztmargin",
    "lzt_client",
    "setlztkey",
    "adm_lzt_settings",
    "temporasms_service_",
    "lzt_reset",
)

# Strings that are code, not prose: callback data, settings keys, command
# names and regex patterns.  These are never rendered to a user.
_IDENT_LIKE = re.compile(r"^[A-Za-z0-9_|.\-:/^$()\\\[\]?+*{}@\s]+$")


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    body[0].value, ast.Constant) and isinstance(
                    body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def test_no_brand_in_user_text():
    leaks = []
    for path in sorted((ROOT / "plugins").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        skip = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)):
                continue
            if id(node) in skip:
                continue
            text = node.value
            low = text.lower()
            if not any(b in low for b in BRANDS):
                continue
            # Remove code tokens (commands, module names, env vars) before
            # checking, so one allowed token can't mask a real leak elsewhere.
            probe = low
            for a in ALLOWED:
                probe = probe.replace(a.lower(), "")
            if not any(b in probe for b in BRANDS):
                continue
            # Skip code identifiers (callback data, keys, commands, regexes):
            # they have no spaces and no sentence punctuation.
            if " " not in text.strip() and not any(c in text for c in ".,!"):
                continue
            # Command names / callback ids embedded in prose are fine.
            if text.lstrip().startswith(("/", "^")):
                continue
            leaks.append(f"{path.name}:{node.lineno}: {text[:70]!r}")
    check("no provider brand in user-facing text", not leaks, leaks[:10])


def test_panel_word_is_used():
    src = (ROOT / "plugins" / "servers.py").read_text(encoding="utf-8")
    check("servers screen says Panel", "Panel" in src)


def test_error_message_is_clean():
    from utils import temporasms
    import inspect
    source = inspect.getsource(temporasms)
    check("no-live-numbers message is branded-free",
          "TemporaSMS has no live numbers" not in source)


def main():
    test_no_brand_in_user_text()
    test_panel_word_is_used()
    test_error_message_is_clean()
    print(f"OK {PASS} checks passed")


if __name__ == "__main__":
    main()
