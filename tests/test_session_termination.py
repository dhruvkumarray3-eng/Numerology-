"""Tests for the "Terminate Other Sessions" device manager.

Run from the repository root:

    python3 tests/test_session_termination.py

The button previously rendered on the OTP card but had no callback handler,
so it silently did nothing.  These tests lock in:

  1. Authorization metadata is rendered and listed correctly.
  2. The device list exposes a selectable terminate button per device.
  3. "Terminate all others" keeps the newest buyer device + panel session.
  4. "Keep only panel device" terminates every non-panel session.
  5. ResetAuthorizationRequest is actually sent for each hash.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "termination-test")
os.environ.setdefault("BOT_TOKEN", "123:termination-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plugins.buy as buy  # noqa: E402
from telethon.tl.functions.account import ResetAuthorizationRequest  # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1
    print(f"PASS {label}")


def auth(hash_, device, platform, created, current=False, country="India"):
    return SimpleNamespace(
        hash=hash_,
        device_model=device,
        platform=platform,
        system_version="Android 14",
        app_name="Telegram",
        date_created=created,
        country=country,
        region="",
        current=current,
    )


def sample_auths():
    now = datetime(2026, 10, 1, 12, 0, 0)
    return [
        auth(1, "Panel-Node", "Linux", now - timedelta(days=30), current=True),
        auth(2, "Old-Laptop", "Windows", now - timedelta(days=10)),
        auth(3, "Buyer-Phone", "Android", now - timedelta(minutes=2)),
        auth(4, "Tablet", "iOS", now - timedelta(days=3)),
    ]


class FakeClient:
    def __init__(self, auths):
        self.auths = auths
        self.calls = []

    def is_connected(self):
        return True

    async def connect(self):
        return None

    async def is_user_authorized(self):
        return True

    async def __call__(self, request):
        self.calls.append(request)
        if request.__class__.__name__ == "GetAuthorizationsRequest":
            return SimpleNamespace(authorizations=self.auths)
        return True


def test_metadata():
    a = sample_auths()[2]
    check("device name", buy._auth_device_name(a) == "Buyer-Phone")
    check("platform", buy._auth_platform(a) == "Android")
    check("country", buy._auth_country(a) == "India")
    check("timestamp parsed", buy._auth_ts(a) > 0)


def test_message_and_buttons():
    auths = sample_auths()
    msg = buy._sessions_message("919999999999", auths)
    check("message lists buyer device", "Buyer-Phone" in msg)
    check("message lists old laptop", "Old-Laptop" in msg)
    check("message hides current panel device from list", "1. Panel-Node" not in msg)
    check("message shows total", "4" in msg)

    btns = buy._sessions_buttons("919999999999", auths)
    flat = [b.data.decode() if isinstance(b.data, bytes) else b.data
            for row in btns for b in row]
    check("has per-device terminate", any(d.startswith("reset_one|919999999999|") for d in flat))
    check("has terminate-all", "reset_all|919999999999" in flat)
    check("has keep-panel", "reset_panel|919999999999" in flat)
    check("has refresh", "reset_sessions|919999999999" in flat)
    check("has back", "refresh_order|919999999999" in flat)


def test_selection_logic():
    auths = sample_auths()
    keep_newest = buy._hashes_keep_newest(auths)
    # Newest non-panel device is Buyer-Phone (hash 3); kill 2 and 4.
    check("keep newest kills older only", sorted(keep_newest) == [2, 4], keep_newest)

    all_others = buy._hashes_all_others(auths)
    check("keep panel kills all non-panel", sorted(all_others) == [2, 3, 4], all_others)

    only_panel = [auth(1, "Panel", "Linux", datetime.now(), current=True)]
    check("no others -> keep newest empty", buy._hashes_keep_newest(only_panel) == [])
    check("no others -> all empty", buy._hashes_all_others(only_panel) == [])


def test_terminate_sends_requests():
    auths = sample_auths()
    client = FakeClient(auths)
    buy.active_orders["919999999999"] = {"client": client}

    done, failed = asyncio.run(buy._terminate_hashes("919999999999", [2, 4]))
    check("terminated count", done == 2, done)
    check("no failures", failed == [], failed)
    check("two reset requests", len(client.calls) == 2, len(client.calls))
    check("requests are ResetAuthorizationRequest",
          all(isinstance(c, ResetAuthorizationRequest) for c in client.calls))
    check("hashes passed correctly", [c.hash for c in client.calls] == [2, 4])

    buy.active_orders.pop("919999999999", None)


def test_load_authorizations_sorts():
    auths = sample_auths()
    client = FakeClient(auths)
    buy.active_orders["918888888888"] = {"client": client}
    loaded, err = asyncio.run(buy._load_authorizations("918888888888"))
    check("load ok", err is None, err)
    check("current first", loaded[0].current is True)
    check("newest non-current next", loaded[1].device_model == "Buyer-Phone", loaded[1].device_model)
    check("cache populated", buy.session_auth_cache["918888888888"] == loaded)
    buy.active_orders.pop("918888888888", None)


def main():
    test_metadata()
    test_message_and_buttons()
    test_selection_logic()
    test_terminate_sends_requests()
    test_load_authorizations_sorts()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
