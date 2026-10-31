"""Regression test: every reply-keyboard screen survives a degraded get_me().

`bot.get_me()` can raise or return None during a reconnect / revoked token /
flood wait.  Before this guard, tapping Profile, Refer or Start in that window
raised AttributeError and the button looked dead.  These checks pin the
defensive wrappers in place.
"""
import os
import sys

os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {detail}")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


helpers_src = read("utils", "helpers.py")
profile_src = read("plugins", "profile.py")
callbacks_src = read("plugins", "callbacks.py")
start_src = read("plugins", "start.py")

print("helpers: safe wrappers")
check("safe_get_me defined", "async def safe_get_me(bot):" in helpers_src)
check("safe_get_me swallows exceptions",
      "except Exception as exc:  # noqa: BLE001 - a missing username is not fatal"
      in helpers_src)
check("get_bot_username defined", "async def get_bot_username(bot):" in helpers_src)
check("get_bot_display_name defined", "async def get_bot_display_name(bot" in helpers_src)

print("call sites no longer dereference get_me() directly")
for label, src in (("profile.py", profile_src),
                   ("callbacks.py", callbacks_src),
                   ("start.py", start_src)):
    check(f"{label}: no bare `me = await bot.get_me()`",
          "me = await bot.get_me()" not in src)
check("profile.py uses get_bot_username",
      "bot_username = await get_bot_username(bot)" in profile_src)
check("callbacks.py uses get_bot_username",
      "bot_username = await get_bot_username(bot)" in callbacks_src)
check("start.py uses safe_get_me", "_me = await safe_get_me(bot)" in start_src)
check("start.py guards a missing bot id",
      'getattr(_me, "id", None) or 0' in start_src)
check("start.py guards a None entity",
      'if user_entity is None:' in start_src)

print("runtime behaviour")
import asyncio  # noqa: E402
from utils.helpers import safe_get_me, get_bot_username, get_bot_display_name  # noqa: E402


class _Boom:
    async def get_me(self):
        raise RuntimeError("session degraded")


class _NoneMe:
    async def get_me(self):
        return None


class _NoUsername:
    async def get_me(self):
        class U:
            id = 777
            username = None
            first_name = None
        return U()


async def _run():
    check("safe_get_me returns None when get_me raises",
          await safe_get_me(_Boom()) is None)
    check("safe_get_me returns None when get_me returns None",
          await safe_get_me(_NoneMe()) is None)
    check("get_bot_username returns '' on raise",
          await get_bot_username(_Boom()) == "")
    check("get_bot_username returns '' when username is None",
          await get_bot_username(_NoUsername()) == "")
    check("get_bot_display_name falls back on raise",
          await get_bot_display_name(_Boom()) == "Store Bot")
    check("get_bot_display_name falls back when first_name is None",
          await get_bot_display_name(_NoUsername()) == "Store Bot")


asyncio.run(_run())

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
