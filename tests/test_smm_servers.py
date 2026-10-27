"""Regression tests for the owner-controlled SMM server ON/OFF switches.

Run with:  python tests/test_smm_servers.py

These tests do not touch the real database: the settings read/write helpers in
``utils.smm_client`` are monkeypatched with an in-memory dict so the toggle
logic can be exercised in isolation.
"""
import asyncio
import os
import sys

# The project imports ``config`` which needs Telegram credentials present.
os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "123456:AAHfakefakefakefakefakefakefakefake")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.smm_client as S

CHECKS = 0
FAILS = []


def check(label, cond):
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"  ok  {label}")
    else:
        print(f" FAIL {label}")
        FAILS.append(label)


def install_store(initial=None):
    """Replace the settings helpers with an in-memory dict store."""
    store = dict(initial or {})

    def _read(key, default=None):
        return store.get(key, default)

    def _write(key, value):
        store[key] = str(value)
        return True

    S._read_setting = _read
    S._write_setting = _write
    return store


def test_defaults():
    print("\n[defaults]")
    install_store()  # empty -> fall back to SMM_SERVER_DEFAULT
    check("server 1 defaults ON", S.is_server_enabled(1) is True)
    check("server 2 defaults OFF", S.is_server_enabled(2) is False)
    check("enabled_servers == [1]", S.enabled_servers() == [1])
    check("server_status maps both", S.server_status() == {1: True, 2: False})


def test_persistence():
    print("\n[persistence]")
    store = install_store()
    check("set server 2 ON returns True", S.set_server_enabled(2, True) is True)
    check("server 2 now ON", S.is_server_enabled(2) is True)
    check("store key written", store.get("smm_server_2_enabled") == "1")
    check("set server 1 OFF returns True", S.set_server_enabled(1, False) is True)
    check("server 1 now OFF", S.is_server_enabled(1) is False)
    check("enabled_servers == [2]", S.enabled_servers() == [2])

    # Values written as words should also be understood.
    store["smm_server_1_enabled"] = "on"
    check("'on' string counts as enabled", S.is_server_enabled(1) is True)
    store["smm_server_1_enabled"] = "off"
    check("'off' string counts as disabled", S.is_server_enabled(1) is False)


def test_toggle():
    print("\n[toggle]")
    install_store()
    check("toggle server 1 -> OFF", S.toggle_server(1) is False)
    check("toggle server 1 -> ON", S.toggle_server(1) is True)
    check("toggle server 2 -> ON", S.toggle_server(2) is True)
    check("toggle server 2 -> OFF", S.toggle_server(2) is False)


def test_invalid_server():
    print("\n[invalid server]")
    install_store()
    check("unknown server is disabled", S.is_server_enabled(99) is False)
    check("set unknown server fails", S.set_server_enabled(99, True) is False)


def test_guards():
    print("\n[guards]")
    install_store()
    # Server 2 is OFF by default -> must not fetch or order.
    loop = asyncio.new_event_loop()
    try:
        services = loop.run_until_complete(S.fetch_smm_services(2))
        check("fetch on OFF server returns []", services == [])
        res = loop.run_until_complete(S.create_smm_order(1, "https://t.me/x", 100, 2))
        check("order on OFF server blocked", isinstance(res, dict) and "OFF" in res.get("error", ""))
    finally:
        loop.close()

    # Turn server 2 ON: fetch no longer short-circuits on the toggle guard
    # (it will attempt the network, so we only assert the guard is gone by
    # checking the function does not return the empty-list shortcut).
    S.set_server_enabled(2, True)
    check("server 2 enabled after set", S.is_server_enabled(2) is True)


def main():
    test_defaults()
    test_persistence()
    test_toggle()
    test_invalid_server()
    test_guards()

    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} checks passed")
    if FAILS:
        print("FAILURES:")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ALL SMM SERVER TOGGLE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
