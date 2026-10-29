"""Tests for the per-service profit engine + the admin Profit & Pricing panel.

Run from the repository root:

    python3 tests/test_profit_admin.py
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "profit-test")
os.environ.setdefault("BOT_TOKEN", "123:profit-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import markup as mk                     # noqa: E402
from plugins import profit_admin as pa             # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


class FakeEvent:
    def __init__(self, uid=1):
        self.sender_id = uid
        self.text = None
        self.btns = None
        self.answers = []

    async def edit(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def respond(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def reply(self, text, buttons=None, **kw):
        self.text, self.btns = text, buttons

    async def answer(self, *a, **k):
        self.answers.append(a)


def all_buttons(btns):
    for row in btns or []:
        for b in row:
            yield b


def button_icon(b):
    st = getattr(b, "style", None)
    return getattr(st, "icon", None)


def main():
    # ---------------------------------------------------------------- engine
    check("five services registered", len(mk.SERVICES) == 5, mk.SERVICES)
    for svc in ("whatsapp", "numchange", "allotp", "smm", "lzt"):
        check(f"{svc} in SERVICES", svc in mk.SERVICES)

    # default: everything inherits the global rule
    mk.reset_all_markup()
    for svc in mk.SERVICE_ORDER:
        cfg = mk.get_service_config(svc)
        check(f"{svc} starts as global", cfg["override"] is False, cfg)

    # global rule is 25% by default -> 100 becomes 125
    b = mk.service_price_breakdown(100, "whatsapp")
    check("global 25% on 100", b["inr"] == 125.0, b)
    check("global profit 25", b["profit_inr"] == 25.0, b)
    check("usdt conversion present", b["usdt"] > 0, b)

    # per-service percent override
    mk.set_service_markup("smm", mode="percent", percent=40)
    smm = mk.service_price_breakdown(100, "smm")
    wa = mk.service_price_breakdown(100, "whatsapp")
    check("smm override 40%", smm["inr"] == 140.0, smm)
    check("smm profit 40", smm["profit_inr"] == 40.0, smm)
    check("whatsapp unaffected", wa["inr"] == 125.0, wa)
    check("smm override flagged", mk.get_service_config("smm")["override"] is True)

    # per-service fixed INR override
    mk.set_service_markup("whatsapp", mode="fixed", fixed=35, currency="INR")
    check("whatsapp fixed +35", mk.service_price_breakdown(100, "whatsapp")["inr"] == 135.0)

    # per-service fixed USDT override (converted at the live rate)
    mk.set_service_markup("lzt", mode="fixed", fixed=1, currency="USD")
    rate = mk.get_usdt_rate()
    lzt = mk.service_price_breakdown(100, "lzt")
    check("lzt fixed 1 USDT in INR", abs(lzt["profit_inr"] - rate) < 0.01, lzt)

    # reset one service
    mk.reset_service_markup("smm")
    check("smm reset to global", mk.get_service_config("smm")["override"] is False)
    check("smm back to 125", mk.service_price_breakdown(100, "smm")["inr"] == 125.0)

    # reset everything
    mk.reset_all_markup()
    for svc in mk.SERVICE_ORDER:
        check(f"{svc} reset", mk.get_service_config(svc)["override"] is False)

    # ------------------------------------------------- wiring: product panels
    import plugins.product_panels as pp

    mk.set_service_markup("allotp", mode="percent", percent=100)
    check("panel _display_inr uses service",
          pp._display_inr(100, None, "allotp") == 200.0)
    check("panel _display_inr global fallback",
          pp._display_inr(100, None, "whatsapp") == 125.0)
    label = pp._price_label(100, 1, None, "allotp")
    check("panel label has INR + USDT", "\u20b9" in label and "USDT" in label, label)
    mk.reset_all_markup()

    # -------------------------------------------------------- wiring: SMM
    import utils.smm_client as smm_mod

    original = smm_mod.get_service_panel_rate
    smm_mod.get_service_panel_rate = lambda service, server=1: 100.0
    try:
        mk.set_service_markup("smm", mode="percent", percent=50)
        check("smm rate uses override", smm_mod.get_service_inr_rate({}, 1) == 150.0,
              smm_mod.get_service_inr_rate({}, 1))
        check("smm profit uses override", smm_mod.get_service_profit_per_1k({}, 1) == 50.0)
        mk.reset_all_markup()
        check("smm rate back to global", smm_mod.get_service_inr_rate({}, 1) == 125.0)
    finally:
        smm_mod.get_service_panel_rate = original

    # -------------------------------------------------------- wiring: LZT
    import database

    mk.set_service_markup("lzt", mode="percent", percent=60)
    check("lzt margin uses override", database._apply_owner_margin(100) == 160.0,
          database._apply_owner_margin(100))
    mk.reset_all_markup()
    check("lzt margin back to global", database._apply_owner_margin(100) == 125.0)

    # ------------------------------------------------------------ admin UI
    async def ui():
        e = FakeEvent()
        await pa.show_profit_home(e)
        check("home has premium emojis", e.text.count("<tg-emoji") >= 4, e.text.count("<tg-emoji"))
        check("home mentions INR and USDT", "INR" in e.text and "USDT" in e.text)
        check("home lists all services",
              all(mk.SERVICES[s] in e.text for s in mk.SERVICE_ORDER))
        btns = list(all_buttons(e.btns))
        check("home has 5 service buttons + 4 actions", len(btns) == 9, len(btns))
        check("every home button has an icon",
              all(button_icon(b) for b in btns),
              [b.text for b in btns if not button_icon(b)])
        check("reset-all button present",
              any(b.data == b"pf_resetall" for b in btns))
        check("back to admin present",
              any(b.data == b"adm_adminmain" for b in btns))

        # each service screen
        for svc in mk.SERVICE_ORDER:
            e = FakeEvent()
            await pa.show_service(e, svc)
            check(f"{svc} screen emojis", e.text.count("<tg-emoji") >= 3)
            check(f"{svc} screen preview", "cost" in e.text or "preview" in e.text.lower())
            btns = list(all_buttons(e.btns))
            check(f"{svc} buttons all have icons", all(button_icon(b) for b in btns),
                  [b.text for b in btns if not button_icon(b)])
            check(f"{svc} has percent button",
                  any(b.data == f"pf_set|{svc}|percent".encode() for b in btns))

        # global screen
        e = FakeEvent()
        await pa.show_global(e)
        check("global screen emojis", e.text.count("<tg-emoji") >= 3)
        check("global has reset-free back", any(b.data == b"pf_home" for b in all_buttons(e.btns)))

        # live preview
        e = FakeEvent()
        await pa.show_preview(e, 100)
        check("preview shows cost", "\u20b9100" in e.text)
        check("preview shows all services", all(mk.SERVICES[s] in e.text for s in mk.SERVICE_ORDER))
        check("preview shows USDT", "USDT" in e.text)
        check("preview shows profit", "you keep" in e.text)
        btns = list(all_buttons(e.btns))
        check("preview presets present",
              any(b.data == b"pf_prev|100" for b in btns), [b.data for b in btns])
        check("preview all buttons have icons", all(button_icon(b) for b in btns))

        # single-service preview
        e = FakeEvent()
        await pa.show_preview(e, 250, "smm")
        check("service preview only shows that service",
              mk.SERVICES["smm"] in e.text and mk.SERVICES["whatsapp"] not in e.text)

    asyncio.run(ui())

    # ------------------------------------------- admin panel entry point
    import plugins.admin as adm
    src = Path(adm.__file__).read_text(encoding="utf-8")
    check("admin panel has Profit & Pricing button", '"pf_home"' in src)
    check("admin header shows profit rule", "_profit_rule" in src)
    check("admin header shows USDT rate", "_usdt_rate" in src)
    check("admin header shows earned profit", "_earned" in src)

    # ------------------------------------------- plugin registration
    init_src = (ROOT / "plugins" / "__init__.py").read_text(encoding="utf-8")
    check("profit_admin imported", "register_profit_admin" in init_src)
    check("profit_admin registered",
          '("profit_admin", register_profit_admin)' in init_src
          or "register_profit_admin(bot)" in init_src)

    # ------------------------------------------- handlers wired
    registered = []

    class FakeBot:
        def on(self, *a, **k):
            def deco(fn):
                registered.append(fn.__name__)
                return fn
            return deco

    pa.register_profit_admin(FakeBot())
    for name in ("cb_pf_home", "cb_pf_svc", "cb_pf_global", "cb_pf_preview",
                 "cb_pf_set", "cb_pf_gset", "cb_pf_off", "cb_pf_resetall",
                 "msg_pf_input"):
        check(f"handler {name} registered", name in registered, registered)

    # ------------------------------------------- end-to-end click/type flow
    handlers = []

    class RecBot:
        def on(self, ev, **kw):
            def deco(fn):
                m = getattr(ev, "match", None)
                handlers.append((getattr(m, "__self__", m), fn))
                return fn
            return deco

    pa.register_profit_admin(RecBot())

    class ClickEvent(FakeEvent):
        def __init__(self, data=b"", text=None, uid=1):
            super().__init__(uid)
            self._data = data
            self.text = text

        @property
        def data(self):
            return self._data

        @property
        def pattern_match(self):
            pat = getattr(self._pat, "pattern", self._pat)
            if hasattr(pat, "__self__"):
                pat = pat.__self__
            if isinstance(pat, str):
                pat = pat.encode()
            return __import__("re").match(pat, self._data)

    def handler(name):
        return next(fn for _, fn in handlers if fn.__name__ == name)

    def click(name, data):
        e = ClickEvent(data=data)
        e._pat = next(m for m, fn in handlers if fn.__name__ == name)
        return e, handler(name)

    async def flow():
        mk.reset_all_markup()

        e, fn = click("cb_pf_svc", b"pf_svc|smm")
        await fn(e)
        check("flow: smm screen opens", "SMM Services" in e.text)

        e, fn = click("cb_pf_set", b"pf_set|smm|percent")
        await fn(e)
        check("flow: percent prompt state", pa.pf_state[1]["field"] == "percent")

        e = ClickEvent(text="40")
        try:
            await handler("msg_pf_input")(e)
        except Exception as exc:
            check("flow: StopPropagation raised", type(exc).__name__ == "StopPropagation", exc)
        cfg = mk.get_service_config("smm")
        check("flow: smm override applied", cfg["override"] and cfg["percent"] == 40.0, cfg)
        check("flow: screen refreshed with 40%", "40%" in e.text)

        e, fn = click("cb_pf_off", b"pf_off|smm")
        await fn(e)
        check("flow: override removed", mk.get_service_config("smm")["override"] is False)

        e, fn = click("cb_pf_gset", b"pf_gset|percent")
        await fn(e)
        e = ClickEvent(text="30")
        try:
            await handler("msg_pf_input")(e)
        except Exception as exc:
            check("flow: global StopPropagation", type(exc).__name__ == "StopPropagation", exc)
        check("flow: global percent 30", mk.get_markup_config()["percent"] == 30.0)

        e, fn = click("cb_pf_prevask", b"pf_prevask")
        await fn(e)
        e = ClickEvent(text="250")
        try:
            await handler("msg_pf_input")(e)
        except Exception as exc:
            check("flow: preview StopPropagation", type(exc).__name__ == "StopPropagation", exc)
        check("flow: custom preview 250", "250" in e.text and "you keep" in e.text)

        e, fn = click("cb_pf_resetall", b"pf_resetall")
        await fn(e)
        check("flow: reset restores 25%", mk.get_markup_config()["percent"] == 25.0)
        check("flow: reset clears overrides",
              all(not mk.get_service_config(s)["override"] for s in mk.SERVICE_ORDER))

        # admin panel renders with the live profit snapshot
        import plugins.admin as adm
        e = FakeEvent(uid=1)
        await adm.admin_panel_handler(e)
        check("admin panel renders", e.text is not None)
        check("admin panel shows profit rule", "profit" in e.text.lower())
        check("admin panel shows USDT rate", "USDT" in e.text)
        check("admin panel has pf_home button",
              any(b.data == b"pf_home" for b in all_buttons(e.btns)))

    asyncio.run(flow())

    print(f"OK: {PASS} checks passed")


if __name__ == "__main__":
    main()
