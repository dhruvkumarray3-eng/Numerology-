"""Tests for the LZT-market-style termination method.

Run from the repository root:

    python3 tests/test_lzt_reset.py

Locks in the official ``POST /{item_id}/telegram-reset-authorizations``
behaviour we mirror from lzt.market:

  1. 200  -> success.
  2. 401  -> invalid token message.
  3. 403 "Too new authorization" -> the 24h Telegram limitation message.
  4. 403 "No permission" -> permission message.
  5. 404  -> item not found.
  6. 429  -> rate-limit message.
  7. Missing item id -> graceful failure without any HTTP call.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "lzt-reset-test")
os.environ.setdefault("BOT_TOKEN", "123:lzt-reset-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import utils.lzt as lzt  # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1
    print(f"PASS {label}")


class FakeResp:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, *a, **k):
        return self._resp


def run_with(status, body):
    """Run telegram_reset_authorizations against a fake HTTP response."""
    client = lzt.LZTClient()
    client.get_token = lambda: "fake-token"  # bypass DB/env lookup
    orig = lzt.aiohttp.ClientSession
    lzt.aiohttp.ClientSession = lambda *a, **k: FakeSession(FakeResp(status, body))
    try:
        return asyncio.run(client.telegram_reset_authorizations("123456"))
    finally:
        lzt.aiohttp.ClientSession = orig


def test_success():
    ok, msg = run_with(200, '{"status": "success"}')
    check("200 -> ok", ok is True, msg)
    check("200 -> mentions reset", "reset" in msg.lower(), msg)


def test_401():
    ok, msg = run_with(401, "unauthorized")
    check("401 -> not ok", ok is False)
    check("401 -> invalid token", "401" in msg and "token" in msg.lower(), msg)


def test_403_too_new():
    ok, msg = run_with(
        403,
        '{"error": "Too new authorization. Wait at least 24 hours after '
        'authorization (Telegram limitation)"}',
    )
    check("403 too-new -> not ok", ok is False)
    check("403 too-new -> 24 hour", "24 hour" in msg.lower(), msg)


def test_403_permission():
    ok, msg = run_with(403, '{"error": "No permission"}')
    check("403 permission -> not ok", ok is False)
    check("403 permission -> permission", "permission" in msg.lower(), msg)


def test_404():
    ok, msg = run_with(404, "not found")
    check("404 -> not ok", ok is False)
    check("404 -> item not found", "404" in msg or "not found" in msg.lower(), msg)


def test_429():
    ok, msg = run_with(429, "rate limited")
    check("429 -> not ok", ok is False)
    check("429 -> rate limit", "429" in msg or "rate" in msg.lower(), msg)


def test_missing_item_id():
    client = lzt.LZTClient()
    ok, msg = asyncio.run(client.telegram_reset_authorizations(None))
    check("no item id -> not ok", ok is False)
    check("no item id -> message", "item id" in msg.lower(), msg)


def main():
    test_success()
    test_401()
    test_403_too_new()
    test_403_permission()
    test_404()
    test_429()
    test_missing_item_id()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
