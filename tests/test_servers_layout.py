"""Regression test for the four-server catalogue layout.

The owner specified exactly four servers on the Servers screen:

    Server-1  Basic TG Account      (mode: bulk)
    Server-2  LZT Connected         (mode: nonspam)
    Server-3  TG Number Change      (mode: numchange)
    Server-4  Buy WhatsApp Account  (mode: whatsapp)

Server-3 and Server-4 must open the *live* TemporaSMS panels (the same ones
used elsewhere in the bot), not a dead placeholder screen.

Run from the repository root:

    python3 tests/test_servers_layout.py
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "servers-test")
os.environ.setdefault("BOT_TOKEN", "123:pricing-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins import servers as srv              # noqa: E402
from plugins import product_panels as pp        # noqa: E402

PASS = 0

EXPECTED = [
    ("Server-1 (Basic TG Account)", "bulk"),
    ("Server-2 (LZT Connected)", "nonspam"),
    ("Server-3 (TG Number Change)", "numchange"),
    ("Server-4 (Buy WhatsApp Account)", "whatsapp"),
]


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


class _FakeBot:
    def __init__(self):
        self.handlers = {}

    def on(self, _event):
        def _deco(fn):
            self.handlers[fn.__name__] = fn
            return fn
        return _deco


class _FakeEvent:
    def __init__(self, mode, uid=999):
        self._mode = mode
        self.sender_id = uid
        self.pattern_match = self

    def group(self, _i):
        return self._mode

    async def answer(self, *a, **k):
        return None


def test_exactly_four_servers():
    # Avoid touching the DB in the test; the default status is what we assert.
    srv.get_server_status = lambda idx, default="on": default
    servers = srv.parse_servers()
    check("four servers", len(servers) == 4, len(servers))
    got = [(s["name"], s["mode"]) for s in servers]
    check("exact names + modes", got == EXPECTED, got)
    check("all default online", all(s["status"] == "on" for s in servers),
          [s["status"] for s in servers])


def test_live_panels_are_wired():
    check("whatsapp panel exists", "whatsapp" in pp.PANELS)
    check("numchange panel exists", "numchange" in pp.PANELS)
    # The two live servers must use the TemporaSMS service filters.
    check("whatsapp service filter",
          pp.PANELS["whatsapp"]["service"] == "whatsapp",
          pp.PANELS["whatsapp"]["service"])
    check("numchange service filter",
          pp.PANELS["numchange"]["service"] == "telegram",
          pp.PANELS["numchange"]["service"])


def test_open_routes_to_live_panel():
    bot = _FakeBot()
    srv.register_servers(bot)
    check("srv_open handler registered", "cb_srv_open" in bot.handlers,
          list(bot.handlers))

    calls = {}

    async def fake_terms(event, key, country=None):
        calls["terms"] = key

    async def fake_countries(event, key, page=1, query=None):
        calls["countries"] = (key, page)

    pp.show_terms = fake_terms
    pp.show_countries = fake_countries
    pp._terms_accepted = lambda uid, key: False

    handler = bot.handlers["cb_srv_open"]

    # Server-4 (whatsapp) with terms not yet accepted -> terms screen.
    asyncio.run(handler(_FakeEvent("whatsapp")))
    check("whatsapp -> terms gate", calls.get("terms") == "whatsapp", calls)

    # Server-3 (numchange) with terms not yet accepted -> terms screen.
    calls.clear()
    asyncio.run(handler(_FakeEvent("numchange")))
    check("numchange -> terms gate", calls.get("terms") == "numchange", calls)

    # Once accepted, both go straight to the live country list.
    pp._terms_accepted = lambda uid, key: True
    calls.clear()
    asyncio.run(handler(_FakeEvent("whatsapp")))
    check("whatsapp -> live countries", calls.get("countries") == ("whatsapp", 1), calls)

    calls.clear()
    asyncio.run(handler(_FakeEvent("numchange")))
    check("numchange -> live countries", calls.get("countries") == ("numchange", 1), calls)


def main():
    test_exactly_four_servers()
    test_live_panels_are_wired()
    test_open_routes_to_live_panel()
    print(f"OK {PASS} checks passed")


if __name__ == "__main__":
    main()
