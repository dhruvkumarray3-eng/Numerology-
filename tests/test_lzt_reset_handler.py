"""End-to-end tests for the "Panel Reset (All Devices)" button.

Run from the repository root:

    python3 tests/test_lzt_reset_handler.py

``utils/lzt.py`` already has unit tests for the HTTP contract
(``tests/test_lzt_reset.py``).  This file locks in the *handler* that the buyer
actually taps, because a correct client is useless if the callback is not
wired, crashes on a stale order, or swallows the 24h Telegram limitation.

Covered:

  1. The handler is registered on the bot.
  2. The button only appears for orders bought from the Panel (is_lzt+item_id).
  3. Success (200) edits the card, clears the cached device list, no crash.
  4. Failure shows a generic customer-safe message AND the live device list,
     so the buyer can still terminate per-device without raw API details.
  5. A non-Panel order is refused politely instead of calling the API.
  6. A stale/inactive order is refused without touching the network.
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "lzt-reset-handler-test")
os.environ.setdefault("BOT_TOKEN", "123:lzt-reset-handler-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plugins.buy as buy  # noqa: E402
import utils.lzt as lzt_mod  # noqa: E402
from utils.states import active_orders  # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1
    print(f"PASS {label}")


PHONE = "919999999999"


class FakeEvent:
    """Minimal stand-in for a Telethon CallbackQuery event."""

    def __init__(self, phone=PHONE, uid=42):
        self.sender_id = uid
        self.pattern_match = SimpleNamespace(
            group=lambda _n: phone.encode("utf-8")
        )
        self.text = ""
        self.btns = []
        self.answers = []
        self.edited = False
        self.responded = False

    async def answer(self, text="", alert=False):
        self.answers.append((text, alert))

    async def edit(self, text, buttons=None, **kw):
        self.text = text
        self.btns = buttons or []
        self.edited = True

    async def respond(self, text, buttons=None, **kw):
        self.text = text
        self.btns = buttons or []
        self.responded = True


def _plain(text):
    """Fold the stylised math-bold headings back to plain ASCII."""
    import unicodedata
    return unicodedata.normalize("NFKC", text or "")


def _patch_reset(fn):
    """The handler imports ``lzt_client`` lazily, so patch the real object."""
    lzt_mod.lzt_client.telegram_reset_authorizations = fn


def flat(btns):
    out = []
    for row in btns or []:
        for b in row:
            data = getattr(b, "data", b"")
            if isinstance(data, bytes):
                data = data.decode("utf-8", "ignore")
            out.append(data)
    return out


def auth(hash_, device, platform, current=False, days=10):
    from datetime import datetime, timedelta
    return SimpleNamespace(
        hash=hash_,
        device_model=device,
        platform=platform,
        system_version="Android 14",
        app_name="Telegram",
        date_created=datetime(2026, 10, 1, 12, 0, 0) - timedelta(days=days),
        country="India",
        region="",
        current=current,
    )


def sample_auths():
    return [
        auth(1, "Panel-Node", "Linux", current=True, days=30),
        auth(2, "Old-Laptop", "Windows", days=10),
        auth(3, "Buyer-Phone", "Android", days=2),
    ]


def setup_order(is_lzt=True, item_id=555):
    active_orders[PHONE] = {
        "is_lzt": is_lzt,
        "item_id": item_id,
        "user_id": 42,
    }


def teardown():
    active_orders.pop(PHONE, None)
    buy.session_auth_cache.pop(PHONE, None)


# ---------------------------------------------------------------------------
# 1. handler is wired
# ---------------------------------------------------------------------------
def test_handler_registered():
    """The callback must exist AND carry the decorator that wires it up."""
    import inspect

    fn = getattr(buy, "cb_lzt_reset", None)
    check("cb_lzt_reset exists", callable(fn))
    check("cb_lzt_reset is async", inspect.iscoroutinefunction(fn))

    src = inspect.getsource(fn)
    check("cb_lzt_reset is decorated with its callback pattern",
          'events.CallbackQuery(pattern=r"^lzt_reset\\|(.+)$")' in src,
          src.splitlines()[0] if src else "")

    # The handler must be attached to the live bot, not just defined.
    from telethon import events
    from config import bot as runtime_bot
    from plugins import register_all_handlers

    register_all_handlers(runtime_bot)
    pairs = list(runtime_bot.list_event_handlers())
    for _cb, b in pairs:
        if not getattr(b, "resolved", True):
            try:
                asyncio.run(b.resolve(runtime_bot))
            except Exception:
                pass
    cbs = [(cb, b) for cb, b in pairs if isinstance(b, events.CallbackQuery)]
    check("callback handlers registered on the bot", len(cbs) > 100, len(cbs))

    mine = [(cb, b) for cb, b in cbs if cb is fn]
    check("our handler object is among them", bool(mine))

    pats = []
    for _cb, b in mine:
        pat = getattr(getattr(b, "match", None), "__self__", None)
        p = getattr(pat, "pattern", "")
        if isinstance(p, bytes):
            p = p.decode("utf-8", "ignore")
        pats.append(p)
    check("our handler is bound to the lzt_reset pattern",
          any(p == r"^lzt_reset\|(.+)$" for p in pats), pats)


# ---------------------------------------------------------------------------
# 2. button only for Panel orders
# ---------------------------------------------------------------------------
def test_button_visibility():
    setup_order(is_lzt=True, item_id=555)
    btns = buy._sessions_buttons(PHONE, sample_auths())
    check("panel reset button shown for LZT order",
          any(d.startswith("lzt_reset|") for d in flat(btns)), flat(btns))

    setup_order(is_lzt=False, item_id=None)
    btns = buy._sessions_buttons(PHONE, sample_auths())
    check("panel reset button hidden for manual order",
          not any(d.startswith("lzt_reset|") for d in flat(btns)), flat(btns))
    teardown()


# ---------------------------------------------------------------------------
# 3. success path
# ---------------------------------------------------------------------------
def test_success():
    setup_order()
    buy.session_auth_cache[PHONE] = sample_auths()

    async def fake_reset(item_id):
        check("item id forwarded to panel", item_id == 555, item_id)
        return True, "OK: authorizations reset"

    _patch_reset(fake_reset)

    ev = FakeEvent()
    asyncio.run(buy.cb_lzt_reset(ev))

    check("success edits the card", ev.edited, ev.text[:80])
    check("success card mentions reset done",
          "PANEL RESET DONE" in _plain(ev.text), ev.text[:200])
    check("success card shows the phone",
          PHONE in ev.text, ev.text[:200])
    check("success clears stale device cache",
          PHONE not in buy.session_auth_cache)
    check("success offers a way back",
          any(d.startswith("refresh_order|") for d in flat(ev.btns)), flat(ev.btns))
    teardown()


# ---------------------------------------------------------------------------
# 4. 403 "Too new authorization" -> generic error + live device list
# ---------------------------------------------------------------------------
def test_fresh_authorization_failure():
    setup_order()

    async def fake_reset(_item_id):
        return False, (
            "Telegram will not let this session be reset yet. A new "
            "authorization must be at least 24 hours old."
        )

    _patch_reset(fake_reset)

    async def fake_load(_phone):
        return sample_auths(), None

    buy._load_authorizations = fake_load

    ev = FakeEvent()
    asyncio.run(buy.cb_lzt_reset(ev))

    check("failure raises an alert", bool(ev.answers), ev.answers)
    check("alert uses generic Panel wording",
          any("The Panel could not reset sessions" in (t or "")
              for t, _ in ev.answers), ev.answers)
    check("alert hides the raw API reason",
          all("24 hours" not in (t or "") for t, _ in ev.answers), ev.answers)
    check("failure edits the card", ev.edited, ev.text[:80])
    check("failure card mentions reset failed",
          "PANEL RESET FAILED" in _plain(ev.text), ev.text[:200])
    check("failure card lists live devices",
          "ACTIVE DEVICES" in _plain(ev.text), ev.text[:300])
    check("failure card names a real device",
          "Old-Laptop" in ev.text, ev.text[:300])
    check("failure offers back to devices",
          any(d.startswith("reset_sessions|") for d in flat(ev.btns)), flat(ev.btns))
    teardown()


# ---------------------------------------------------------------------------
# 5. non-Panel order refused
# ---------------------------------------------------------------------------
def test_non_lzt_order():
    setup_order(is_lzt=False, item_id=None)
    called = {"n": 0}

    async def fake_reset(_item_id):
        called["n"] += 1
        return True, "should not happen"

    _patch_reset(fake_reset)

    ev = FakeEvent()
    asyncio.run(buy.cb_lzt_reset(ev))

    check("manual order does not call the API", called["n"] == 0, called)
    check("manual order gets an info alert",
          any("only available" in (t or "").lower() for t, _ in ev.answers), ev.answers)
    teardown()


# ---------------------------------------------------------------------------
# 6. inactive order refused
# ---------------------------------------------------------------------------
def test_inactive_order():
    active_orders.pop(PHONE, None)
    called = {"n": 0}

    async def fake_reset(_item_id):
        called["n"] += 1
        return True, "should not happen"

    _patch_reset(fake_reset)

    ev = FakeEvent()
    asyncio.run(buy.cb_lzt_reset(ev))

    check("inactive order does not call the API", called["n"] == 0, called)
    check("inactive order gets an alert",
          any("no longer active" in (t or "").lower() for t, _ in ev.answers), ev.answers)


def main():
    test_handler_registered()
    test_button_visibility()
    test_success()
    test_fresh_authorization_failure()
    test_non_lzt_order()
    test_inactive_order()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
