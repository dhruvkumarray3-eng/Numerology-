"""Every product entry point must show its own "Agree & Continue" first.

Owner requirement (from the screen recording):

    WhatsApp, TG Number Change, All Apps OTP and the Good Quality / Cheap TG
    buttons must open the terms screen first; only after "Agree & Continue"
    does the real content (country list / app list / account catalogue) appear.

This test locks in that wiring without touching the network or Telegram:

1. ``PANELS["accounts"]`` exists with terms + guide text.
2. ``show_accounts_terms`` renders an ``pp_agree|accounts`` button and stores
   the pending action so the click resumes the right screen.
3. ``_run_pending`` dispatches countries / filters / years correctly.
4. The buy.py and servers.py entry handlers actually call the gate when the
   panel has not been accepted (source-level guard).

Run: API_ID=1 API_HASH=x BOT_TOKEN=1:x python3 tests/test_terms_gate_entrypoints.py
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test-hash")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")

from plugins import product_panels as PP
from plugins import buy
from plugins import servers

CHECKS = []


def check(name, cond, extra=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


class _FakeEvent:
    def __init__(self, uid=555000111):
        self.sender_id = uid
        self.edited = []
        self.responded = []

    async def answer(self, *a, **kw):
        pass

    async def edit(self, text=None, buttons=None, **kw):
        self.edited.append((text, buttons))

    async def respond(self, text=None, buttons=None, **kw):
        self.responded.append((text, buttons))
        return self


def _button_datas(buttons):
    out = []
    for row in buttons or []:
        for b in row:
            data = getattr(b, "data", None)
            if data is None:
                data = getattr(b, "button", None)
            out.append(data)
    return out


def test_accounts_panel_exists():
    p = PP.PANELS.get("accounts")
    check("accounts panel exists", p is not None)
    if not p:
        return
    check("accounts has tc_title", bool(p.get("tc_title")))
    check("accounts has tc_body", bool(p.get("tc_body")))
    check("accounts has guide", bool(p.get("guide")))
    check("accounts is not a TemporaSMS panel", "service" not in p)


def test_show_accounts_terms_renders_agree_and_stores_pending():
    PP._TC_MEMORY.clear()
    ev = _FakeEvent()
    action = {"fn": "countries", "mode": "nonspam", "page": 1}
    asyncio.run(PP.show_accounts_terms(ev, action))
    rendered = ev.edited or ev.responded
    check("terms screen rendered", len(rendered) == 1, rendered)
    datas = _button_datas(rendered[0][1] if rendered else [])
    check("agree button present", b"pp_agree|accounts" in datas, datas)
    check("pending stored", PP._pop_pending(ev.sender_id) == action)


def test_run_pending_dispatch():
    calls = {}

    async def fake_countries(event, mode, page=1):
        calls["countries"] = (mode, page)

    async def fake_filters(event, page=1):
        calls["filters"] = page

    async def fake_years(event):
        calls["years"] = True

    async def fake_menu(event):
        calls["menu"] = True

    real = (buy.show_countries, buy.show_filters_catalog,
            buy.show_years_catalog, buy.show_buy_menu)
    buy.show_countries = fake_countries
    buy.show_filters_catalog = fake_filters
    buy.show_years_catalog = fake_years
    buy.show_buy_menu = fake_menu
    try:
        ev = _FakeEvent()
        asyncio.run(PP._run_pending(ev, {"fn": "countries", "mode": "spam", "page": 2}))
        check("dispatch countries", calls.get("countries") == ("spam", 2), calls)
        asyncio.run(PP._run_pending(ev, {"fn": "filters", "page": 3}))
        check("dispatch filters", calls.get("filters") == 3, calls)
        asyncio.run(PP._run_pending(ev, {"fn": "years"}))
        check("dispatch years", calls.get("years") is True, calls)
        asyncio.run(PP._run_pending(ev, None))
        check("dispatch fallback menu", calls.get("menu") is True, calls)
    finally:
        (buy.show_countries, buy.show_filters_catalog,
         buy.show_years_catalog, buy.show_buy_menu) = real


def test_buy_handlers_gate():
    src = inspect.getsource(buy)
    for fn in ("cb_pg_c", "cb_pg_filters", "cb_by_years_menu"):
        start = src.find(f"async def {fn}")
        check(f"{fn} exists", start != -1)
        if start == -1:
            continue
        body = src[start:start + 700]
        check(f"{fn} checks terms", "_terms_accepted" in body and "show_accounts_terms" in body)


def test_servers_gate_accounts():
    src = inspect.getsource(servers)
    start = src.find("async def cb_srv_open")
    check("cb_srv_open exists", start != -1)
    body = src[start:start + 1600]
    check("servers gate accounts", "show_accounts_terms" in body and '"accounts"' in body)


def main():
    test_accounts_panel_exists()
    test_show_accounts_terms_renders_agree_and_stores_pending()
    test_run_pending_dispatch()
    test_buy_handlers_gate()
    test_servers_gate_accounts()

    failed = [c for c in CHECKS if not c[1]]
    print(f"\nPASSED: {len(CHECKS) - len(failed)}  FAILED: {len(failed)}  TOTAL: {len(CHECKS)}")
    if failed:
        for n, _ok, extra in [(c[0], c[1], "") for c in failed]:
            print("  FAILED:", n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
