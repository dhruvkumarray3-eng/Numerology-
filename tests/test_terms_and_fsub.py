"""Locks in the two owner requirements:

1. EVERY product entry point shows its own "Agree & Continue" screen first.
2. The bot re-verifies channel membership on EVERY interaction, so a user who
   leaves is asked to rejoin on the next tap, and a user who stays gets all
   buttons working.
"""
import ast
import asyncio
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


pp = read("plugins", "product_panels.py")
manual = read("plugins", "manual_accounts.py")
allapps = read("plugins", "all_apps.py")
buy = read("plugins", "buy.py")
servers = read("plugins", "servers.py")
start = read("plugins", "start.py")
guard = read("plugins", "fsub_guard.py")
main_src = read("main.py")

print("1. Terms pages exist for the two previously ungated buttons")
import plugins.product_panels as PP  # noqa: E402

check("EXTRA_TC defined", hasattr(PP, "EXTRA_TC"))
check("mtg page present", "mtg" in getattr(PP, "EXTRA_TC", {}))
check("allapps page present", "allapps" in getattr(PP, "EXTRA_TC", {}))
for key in ("mtg", "allapps"):
    page = PP.EXTRA_TC.get(key, {})
    check(f"{key}: has tc_title", bool(page.get("tc_title")))
    check(f"{key}: has tc_body", bool(page.get("tc_body")))
    check(f"{key}: has guide", bool(page.get("guide")))
    check(f"{key}: has icon", bool(page.get("icon")))
check("is_terms_key() exported", callable(getattr(PP, "is_terms_key", None)))
check("is_terms_key('mtg')", PP.is_terms_key("mtg"))
check("is_terms_key('allapps')", PP.is_terms_key("allapps"))
check("is_terms_key('whatsapp')", PP.is_terms_key("whatsapp"))
check("is_terms_key('nope') is False", not PP.is_terms_key("nope"))

print("2. Every entry point the owner listed is gated")
check("pp_open|whatsapp gated (cb_open -> show_terms)",
      "if not _terms_accepted(uid, key):" in pp and "show_terms(e, key)" in pp)
check("pp_open|allotp gated (same cb_open path)", "is_terms_key(key)" in pp)
check("srv_open|numchange gated", "if not _terms_accepted(e.sender_id, mode):" in servers)
check("Good/Cheap TG gated (cb_pg_c -> accounts gate)",
      'if not _terms_accepted(event.sender_id, "accounts"):' in buy)
check("mtg_home gated", '_terms_accepted(uid, "mtg")' in manual)
check("all_apps_menu gated", '_terms_accepted(e.sender_id, "allapps")' in allapps)
check("mtg gate shows show_terms(e, 'mtg')", 'show_terms(e, "mtg")' in manual)
check("allapps gate shows show_terms(e, 'allapps')", 'show_terms(e, "allapps")' in allapps)
check("mtg gate queues the follow-up screen",
      '_set_pending(uid, {"fn": "mtg", "page": 1})' in manual)
check("allapps gate queues the follow-up screen",
      '_set_pending(e.sender_id, {"fn": "all_apps"})' in allapps)

print("3. Agree button actually continues into the right screen")
check("_run_pending handles fn=mtg", 'if fn == "mtg":' in pp)
check("_run_pending handles fn=all_apps", 'if fn == "all_apps":' in pp)
check("cb_agree routes EXTRA_TC keys through the pending queue",
      'if key == "accounts" or key in EXTRA_TC:' in pp)
check("cb_open has an EXTRA_TC branch", "if key in EXTRA_TC:" in pp)
check("show_terms accepts extra pages", "p = _tc_page(key)" in pp)
check("show_guide accepts extra pages",
      pp.count("p = _tc_page(key)") >= 2)
check("Agree & Continue label present", "Agree & Continue" in pp)

print("4. Force-subscribe guard")
check("guard module exists", "register_fsub_guard" in guard)
check("guard re-verifies via check_channel_joined",
      "check_channel_joined(bot, uid, _is_admin_safe)" in guard)
check("guard builds a join screen", "get_unjoined_channels(bot, uid)" in guard)
check("guard stops the update chain", "events.StopPropagation" in guard)
check("guard skips /start", 'SKIP_TEXTS = ("/start",)' in guard)
check("guard skips verify_join", 'SKIP_CALLBACKS = (b"verify_join",)' in guard)
check("guard only inspects private incoming messages",
      "e.is_private and not e.out" in guard)
check("guard has a success cache", "JOIN_CACHE_TTL" in guard)
check("failures are never cached (only _remember on success)",
      guard.count("_remember(uid)") >= 2)
check("admin bypass cannot raise", "def _is_admin_safe(uid):" in guard)
check("guard answers the callback spinner",
      'await event.answer(' in guard)

print("5. Guard is registered before every other handler")
check("main.py registers the guard", "register_fsub_guard(bot)" in main_src)
check("guard registered at step 4a0",
      "# 4a0. Force-subscribe guard" in main_src)
guard_idx = main_src.index("register_fsub_guard(bot)")
router_idx = main_src.index("register_menu_router(bot)")
plugins_idx = main_src.index("register_all_handlers(bot)")
check("guard before menu router", guard_idx < router_idx)
check("guard before all plugins", guard_idx < plugins_idx)
check("no module-level @bot.on left in deposit.py",
      "\n@bot.on(" not in read("plugins", "deposit.py"))
check("BEP20 handler attached from register_deposit",
      'bot.on(events.CallbackQuery(pattern=r"^dep_choose_BEP20$"))(cb_choose_bep20)'
      in read("plugins", "deposit.py"))

print("6. Runtime: guard allows/denies correctly")
import plugins.fsub_guard as G  # noqa: E402


class _Bot:
    pass


async def _runtime():
    G._joined_ok.clear()

    async def joined(bot, uid, is_admin_func):
        return True

    async def not_joined(bot, uid, is_admin_func):
        return False

    orig = G.check_channel_joined

    G.check_channel_joined = joined
    check("joined user is allowed", await G._needs_join(_Bot(), 111) is False)
    check("success is cached", G._trusted(111) is True)
    check("cached user is not re-queried", await G._needs_join(_Bot(), 111) is False)

    G.check_channel_joined = not_joined
    check("a cached user stays allowed within TTL",
          await G._needs_join(_Bot(), 111) is False)
    G.forget(111)
    check("after forget, a leaver is blocked",
          await G._needs_join(_Bot(), 111) is True)
    check("a leaver is not cached", G._trusted(111) is False)
    check("second check still blocks", await G._needs_join(_Bot(), 111) is True)

    async def boom(bot, uid, is_admin_func):
        raise RuntimeError("telegram down")

    G.check_channel_joined = boom
    check("an API error never locks the user out",
          await G._needs_join(_Bot(), 222) is False)

    G.check_channel_joined = orig


asyncio.run(_runtime())

print("7. Runtime: every terms screen really renders with an Agree button")


class _Msg:
    def __init__(self, t):
        self.raw_text = t
        self.text = t
        self.message = t
        self.buttons = None
        self.id = 1


class _Ev:
    def __init__(self, uid):
        self.sender_id = uid
        self.chat_id = uid
        self.raw_text = ""
        self.text = ""
        self.out = False
        self.is_private = True
        self.message = _Msg("")
        self.pattern_match = None
        self.sent = []

    async def respond(self, message=None, buttons=None, **k):
        self.sent.append((message, buttons))
        return _Msg(message or "")

    async def edit(self, message=None, buttons=None, **k):
        self.sent.append((message, buttons))
        return _Msg(message or "")

    async def reply(self, message=None, buttons=None, **k):
        return await self.respond(message, buttons=buttons)

    async def answer(self, *a, **k):
        return None

    async def delete(self, *a, **k):
        return None


def _labels(btns):
    out = []
    for row in (btns or []):
        for b in row:
            t = getattr(b, "text", None) or getattr(getattr(b, "button", None), "text", None)
            if t:
                out.append(str(t))
    return out


async def _render_all():
    for key in ("mtg", "allapps", "whatsapp", "allotp", "numchange", "accounts"):
        ev = _Ev(700000 + abs(hash(key)) % 1000)
        await PP.show_terms(ev, key)
        msg, btns = ev.sent[-1]
        labels = _labels(btns)
        check(f"{key}: terms title rendered",
              PP._tc_page(key)["tc_title"] in msg)
        check(f"{key}: Agree & Continue button rendered",
              any("Agree" in l for l in labels), labels)
        check(f"{key}: Cancel button rendered",
              any("Cancel" in l for l in labels), labels)


asyncio.run(_render_all())

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
