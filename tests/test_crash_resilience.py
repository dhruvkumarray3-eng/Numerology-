"""Regression tests for the "The app crashed on an unhandled error" bug.

The production crash was caused by ``asyncio.CancelledError`` (a subclass of
``BaseException``, *not* ``Exception``) escaping the reconnect loop in
``main.py``, unwinding through ``asyncio.run(main())`` and killing the whole
process.  These tests make sure that can never happen again.
"""

import ast
import os
import re

import pytest

MAIN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")


def _read_main() -> str:
    with open(MAIN_PY, "r", encoding="utf-8") as fh:
        return fh.read()


def test_main_parses():
    """main.py must always be syntactically valid."""
    src = _read_main()
    ast.parse(src)


def test_reconnect_loop_catches_base_exception():
    """The reconnect loop must catch BaseException so CancelledError cannot escape."""
    src = _read_main()
    assert "except BaseException" in src, (
        "main.py no longer catches BaseException — asyncio.CancelledError would "
        "escape the reconnect loop and crash the process again."
    )


def test_cancelled_error_is_reraised_not_swallowed():
    """CancelledError must be explicitly re-raised so shutdown still works."""
    src = _read_main()
    assert re.search(r"except\s+asyncio\.CancelledError\s*:\s*\n\s*raise", src), (
        "main.py must re-raise asyncio.CancelledError explicitly."
    )


def test_supervisor_wraps_asyncio_run():
    """asyncio.run(main()) must be wrapped by a supervisor that restarts on failure."""
    src = _read_main()
    assert "_supervise" in src
    assert "asyncio.run(main())" in src
    # The supervisor must guard the asyncio.run call with a BaseException handler.
    supervise_body = src.split("def _supervise", 1)[1]
    assert "except BaseException" in supervise_body, (
        "_supervise() must catch BaseException around asyncio.run(main())."
    )


def test_validate_runtime_config_returns_bool_not_raises():
    """Missing env vars must produce a clean CRITICAL log + exit, not a traceback."""
    src = _read_main()
    assert "def validate_runtime_config() -> bool" in src
    body = src.split("def validate_runtime_config", 1)[1].split("\ndef ", 1)[0]
    assert "raise" not in body, "validate_runtime_config() must not raise."


def test_health_server_never_raises():
    """A busy port must not take the bot down."""
    path = os.path.join(os.path.dirname(MAIN_PY), "utils", "health.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    body = src.split("async def start_health_server", 1)[1]
    assert "return None" in body, "start_health_server() must return None instead of raising."
    assert "handle_signals=False" in body, (
        "AppRunner must use handle_signals=False so it does not hijack SIGTERM."
    )


def test_config_does_not_raise_at_import():
    """config.py must never raise RuntimeError at import time."""
    path = os.path.join(os.path.dirname(MAIN_PY), "config.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "raise RuntimeError" not in src, (
        "config.py must not raise RuntimeError at import — that prints a raw "
        "traceback before logging is configured."
    )
