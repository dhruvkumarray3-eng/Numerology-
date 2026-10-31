"""Regression guard for the high-priority reply-keyboard router.

``plugins/menu_router.py`` is registered *before* every plugin and matches
bottom-keyboard labels by canonical key, so a catch-all (country search, OTP
text input, ...) can never hijack a button tap.  This test locks in:

  1. every label on the real persistent keyboard is matched by the router,
  2. ordinary text ("US", "Stockholm", "12345", ...) is *not* matched,
  3. every ``_dispatch`` branch points at a real, callable target with the
     argument list it is actually called with,
  4. ``main.py`` registers the router before ``register_all_handlers``.
"""
import ast
import importlib
import inspect
import os
import pathlib
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")

CHECKS = []


def check(name, ok, detail=None):
    CHECKS.append((name, bool(ok), detail))


# ---------------------------------------------------------------------------
# 1. Router registration + label matching
# ---------------------------------------------------------------------------
class _FakeBot:
    def __init__(self):
        self.handlers = []

    def on(self, builder):
        def deco(fn):
            self.handlers.append((builder, fn))
            return fn
        return deco


class _FakeEvent:
    def __init__(self, text, uid=123):
        self.raw_text = text
        self.text = text
        self.sender_id = uid
        self.is_private = True
        self.out = False


from plugins import menu_router  # noqa: E402
from utils.keyboards import get_persistent_menu  # noqa: E402

bot = _FakeBot()
menu_router.register_menu_router(bot)

check("router registers exactly one handler", len(bot.handlers) == 1,
      f"got {len(bot.handlers)}")
check("router handler is named menu_label_router",
      bot.handlers and bot.handlers[0][1].__name__ == "menu_label_router")

labels = []
for row in get_persistent_menu(1):
    for btn in row:
        text = getattr(getattr(btn, "button", None), "text", None)
        if text:
            labels.append(text)

check("persistent keyboard has labels", len(labels) >= 10, f"got {len(labels)}")

if bot.handlers:
    builder, _fn = bot.handlers[0]
    func = getattr(builder, "func", None)
    check("router uses a func matcher", func is not None)

    if func is not None:
        matched = 0
        for label in labels:
            try:
                if func(_FakeEvent(label)):
                    matched += 1
                else:
                    check(f"router matches label {label!r}", False)
            except Exception as exc:  # noqa: BLE001
                check(f"router matches label {label!r}", False,
                      f"{type(exc).__name__}: {exc}")
        check(f"router matches all {len(labels)} labels", matched == len(labels),
              f"{matched}/{len(labels)}")

        for text in ("US", "Stockholm", "12345", "hello", "https://t.me/x", "₹500"):
            try:
                hit = bool(func(_FakeEvent(text)))
            except Exception as exc:  # noqa: BLE001
                check(f"router ignores non-label {text!r}", False,
                      f"{type(exc).__name__}: {exc}")
                continue
            check(f"router ignores non-label {text!r}", not hit)

# ---------------------------------------------------------------------------
# 2. Every _dispatch branch resolves to a real callable with the right args
# ---------------------------------------------------------------------------
EXPECTED = {
    ("plugins.callbacks", "send_stock_page"): ["event", "page"],
    ("plugins.profile", "profile_handler"): ["bot", "event"],
    ("plugins.profile", "stats_handler"): ["bot", "event"],
    ("plugins.callbacks", "send_my_orders"): ["event"],
    ("plugins.callbacks", "send_balance"): ["event"],
    ("plugins.callbacks", "show_refer_menu"): ["bot", "event"],
    ("plugins.callbacks", "send_support"): ["event"],
    ("plugins.deposit", "deposit_menu"): ["event"],
    ("plugins.buy", "show_buy_menu"): ["event"],
    ("plugins.start", "send_main_menu"): ["bot", "event", "uid"],
    ("plugins.help_menu", "show_help"): ["event"],
    ("plugins.admin", "admin_panel_handler"): ["event"],
    ("plugins.settings_menu", "show_settings"): ["event"],
    ("plugins.servers", "show_servers"): ["event"],
    ("plugins.tempmail", "show_home"): ["event"],
}

for (mod_name, attr), expected_params in EXPECTED.items():
    try:
        module = importlib.import_module(mod_name)
    except Exception as exc:  # noqa: BLE001
        check(f"{mod_name} imports", False, f"{type(exc).__name__}: {exc}")
        continue
    target = getattr(module, attr, None)
    check(f"{mod_name}.{attr} exists", target is not None)
    if target is None:
        continue
    check(f"{mod_name}.{attr} is callable", callable(target))
    if not callable(target):
        continue
    params = [p.name for p in inspect.signature(target).parameters.values()
              if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)]
    check(f"{mod_name}.{attr} signature matches dispatch",
          params[:len(expected_params)] == expected_params,
          f"got {params}")

# Every ImportFrom inside menu_router must resolve (catches renamed helpers).
router_src = pathlib.Path(ROOT, "plugins", "menu_router.py").read_text(encoding="utf-8")
tree = ast.parse(router_src)
for node in ast.walk(tree):
    if not isinstance(node, ast.ImportFrom) or not node.module:
        continue
    if not node.module.startswith(("plugins", "utils", "database")):
        continue
    try:
        module = importlib.import_module(node.module)
    except Exception as exc:  # noqa: BLE001
        check(f"menu_router import {node.module}", False,
              f"{type(exc).__name__}: {exc}")
        continue
    for alias in node.names:
        check(f"menu_router import {node.module}.{alias.name} resolves",
              hasattr(module, alias.name))

# ---------------------------------------------------------------------------
# 3. main.py registers the router before all other plugins
# ---------------------------------------------------------------------------
main_src = pathlib.Path(ROOT, "main.py").read_text(encoding="utf-8")
router_pos = main_src.find("register_menu_router(bot)")
all_pos = main_src.find("register_all_handlers(bot)")
check("main.py calls register_menu_router", router_pos != -1)
check("main.py calls register_all_handlers", all_pos != -1)
check("menu router is registered before all other plugins",
      router_pos != -1 and all_pos != -1 and router_pos < all_pos,
      f"router@{router_pos} all@{all_pos}")
check("main.py prints menu routing self-test",
      "Menu routing self-test" in main_src)

# ---------------------------------------------------------------------------
# 4. Legacy / stale keyboard glyphs must still route
#
# A reply keyboard lives on the user's phone: after a layout change the old
# one stays on screen until the bot sends a new one.  Older builds used the
# Unicode "letterlike symbols" block (U+2119 P, U+2102 C, U+211D R, U+210D H)
# and fullwidth forms.  Those must fold to the same canonical key, otherwise
# "Profile" stays dead for every user holding a stale keyboard.
# ---------------------------------------------------------------------------
from utils.keyboards import MENU_VERSION, menu_label_key, normalise_menu_text  # noqa: E402

LEGACY = {
    "\u2119\u0280\u1d0f\u0493\u026a\u029f\u1d07": "profile",          # ℙʀᴏғɪʟᴇ
    "\U0001f464 \u2119\u0280\u1d0f\u0493\u026a\u029f\u1d07": "profile",  # 👤 ℙʀᴏғɪʟᴇ
    "\U0001f4ca \U0001d54a\u1d1b\u1d0f\u1d04\u1d0b": "stock",          # 📊 𝕊ᴛᴏᴄᴋ
    "\uff23\uff4c\uff4f\uff53\uff45": "close",                          # Ｃｌｏｓｅ
    "\u2102\U0001d55d\U0001d560\U0001d564\U0001d556": "close",          # ℂ𝕝𝕠𝕤𝕖
    "\U0001f198 Help": "help",                                             # 🆘 Help
}
for label, expected in LEGACY.items():
    got = menu_label_key(label)
    check(f"legacy label {label!r} routes to {expected}", got == expected,
          f"got {got} (folded={normalise_menu_text(label)!r})")

# The SOS emoji must not be expanded to the letters "SOS" by NFKC folding.
check("squared SOS emoji is not expanded",
      "sos" not in normalise_menu_text("\U0001f198 Help"))

check("MENU_VERSION is a positive int", isinstance(MENU_VERSION, int) and MENU_VERSION > 0,
      f"got {MENU_VERSION!r}")

# install_persistent_menu must re-send a stale keyboard.
start_src = pathlib.Path(ROOT, "plugins", "start.py").read_text(encoding="utf-8")
check("start.py compares stored menu version", "get_menu_version(uid) < MENU_VERSION" in start_src)
check("start.py records the installed menu version", "set_menu_version(uid, MENU_VERSION)" in start_src)

db_src = pathlib.Path(ROOT, "database.py").read_text(encoding="utf-8")
check("database exposes get_menu_version", "def get_menu_version(" in db_src)
check("database exposes set_menu_version", "def set_menu_version(" in db_src)
check("users table gets a menu_version column", "ADD COLUMN menu_version" in db_src)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
failed = [c for c in CHECKS if not c[1]]
for name, ok, detail in CHECKS:
    if not ok:
        print(f"FAIL: {name}" + (f"  [{detail}]" if detail is not None else ""))
print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
if failed:
    sys.exit(1)
print("ALL MENU-ROUTER DISPATCH CHECKS PASSED")
