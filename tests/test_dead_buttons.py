"""Regression guard: every button must actually do something.

This suite walks the whole codebase, extracts the callback data of every
inline button, and asserts that a registered ``CallbackQuery`` handler
(or one of the known central dispatchers) matches it.  It also checks a
couple of specific bugs that were found and fixed:

  * ``plugins/deposit.py`` had two buttons whose label was double-escaped,
    so they rendered the literal text ``\\u274C \\U0001D402...`` instead of
    "❌ ᴄᴀɴᴄᴇʟ".
  * ``plugins/buy.py`` passed a payment URL to ``style_btn`` (an inline
    callback button), so tapping "Buy Market Access" did nothing.  It now
    uses ``style_url``.
  * ``cancel_order|`` and ``get_qr_`` buttons had no handler at all.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CHECKS = []


def check(name, cond, detail=None):
    CHECKS.append((name, bool(cond), detail))


PAT_RE = re.compile(
    r'CallbackQuery\([^)]*?pattern\s*=\s*[rb]?(["\'])(.+?)\1', re.S)

# Prefixes handled by a central dispatcher instead of a per-button pattern.
DISPATCHED_PREFIXES = (
    "adm_",      # plugins/admin_actions.py strips "adm_" and routes by name
    "mtg_",      # plugins/manual_accounts.py uses data.startswith(...)
    "dl_",       # ^dl_(telethon|tdata|pyrogram|json)_(.+)
    "bc|",       # ^bc\|([^|]+)\|(.+)
    "by|",       # ^by\|([^|]+)\|([^|]+)\|([^|]+)\|(.+)
    "pg_c|",     # ^pg_c\|([^|]+)\|(\d+)
    "pg_filters|",
    "pp_",       # product panels
    "smm_",      # smm panel
    "aa_",       # all apps
    "src_",      # source codes
    "pnl_",      # panels
    "stk_pg|",
    "ac_",       # admin cleanup
    "srv_off|",
    "reset_one|",
    "pf_",       # profit admin
    "get_qr_",
    "cancel_order|",
    "chg_num|",
    "get_otp_again|",
    "get_code_",
    "finish_order|",
    "reset_sessions|",
)


def _scan():
    patterns = []
    static_data = []      # (data, file, lineno)
    dynamic_prefix = []   # (prefix, file, lineno)
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if ".git" in dirpath or "__pycache__" in dirpath or "/tests" in dirpath:
            continue
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(dirpath, fname)
            rel = os.path.relpath(path, ROOT)
            src = open(path, encoding="utf-8", errors="ignore").read()
            for m in PAT_RE.finditer(src):
                patterns.append(m.group(2).replace("\\", ""))
            try:
                tree = ast.parse(src)
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
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    static_data.append((arg.value, rel, node.lineno))
                elif isinstance(arg, ast.JoinedStr):
                    prefix = ""
                    for part in arg.values:
                        if isinstance(part, ast.Constant):
                            prefix += str(part.value)
                        else:
                            break
                    dynamic_prefix.append((prefix, rel, node.lineno))
    return patterns, static_data, dynamic_prefix


def main():
    patterns, static_data, dynamic_prefix = _scan()
    check("found callback patterns", len(patterns) > 100, len(patterns))
    check("found static button data", len(static_data) > 100, len(static_data))

    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p.encode()))
        except re.error:
            try:
                compiled.append(re.compile(p))
            except re.error:
                pass

    def handled(data):
        for c in compiled:
            try:
                if c.match(data.encode()):
                    return True
            except Exception:
                try:
                    if c.match(data):
                        return True
                except Exception:
                    pass
        return any(data.startswith(p) for p in DISPATCHED_PREFIXES)

    dead = [(d, f, l) for d, f, l in static_data if not handled(d)]
    check("no dead inline buttons", not dead, dead[:10])

    dead_dyn = [
        (p, f, l) for p, f, l in dynamic_prefix
        if not any(p in pat for pat in patterns)
        and not any(p.startswith(x) for x in DISPATCHED_PREFIXES)
    ]
    check("no dead dynamic buttons", not dead_dyn, dead_dyn[:10])

    # ---- specific fixes -------------------------------------------------
    deposit_src = open(os.path.join(ROOT, "plugins", "deposit.py"),
                       encoding="utf-8").read()
    check("deposit has no double-escaped cancel label",
          '\\\\u274C' not in deposit_src)
    check("deposit cancel button uses real emoji",
          '\u274c \U0001D402\U0001D41A\U0001D427\U0001D41C\U0001D41E\U0001D425' in deposit_src)

    buy_src = open(os.path.join(ROOT, "plugins", "buy.py"),
                   encoding="utf-8").read()
    check("market access button is a real URL button",
          'style_url("\\U0001F4B3 Buy Market Access"' in buy_src)
    check("buy.py imports style_url", "style_url" in buy_src.split("\n")[30])
    check("cancel_order handler registered", "cb_cancel_order" in buy_src)
    check("get_qr handler registered", "cb_get_qr" in buy_src)

    # ---- profit panel premium emojis ------------------------------------
    pa_src = open(os.path.join(ROOT, "plugins", "profit_admin.py"),
                  encoding="utf-8").read()
    check("profit panel uses premium emoji helper", "_svc_pe" in pa_src)
    check("profit panel service rows use premium emoji",
          "{_svc_pe(service)} <b>{SERVICES[service]}</b>" in pa_src)

    # ---- admin header premium emojis ------------------------------------
    admin_src = open(os.path.join(ROOT, "plugins", "admin.py"),
                     encoding="utf-8").read()
    check("admin header uses PE_MONEY", "{PE_MONEY} <b>" in admin_src)
    check("admin header uses PE_USDT", "{PE_USDT} <b>1 USDT:" in admin_src)
    check("admin header uses PE_STATS", "{PE_STATS} <b>" in admin_src)

    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
