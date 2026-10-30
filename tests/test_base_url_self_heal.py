"""Tests for the one-time DB self-heal of provider base URLs.

Run from the repository root:

    python3 tests/test_base_url_self_heal.py

Older builds stored website URLs (e.g. https://temporasms.com/api or
https://api.grabmail.io/v1/messages) instead of the real API roots, which made
every request 404.  ``runtime_config.self_heal_base_urls`` must rewrite those
stored values to the canonical API roots exactly once, and leave correct values
untouched.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "selfheal-test")
os.environ.setdefault("BOT_TOKEN", "123:selfheal-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Point the runtime store at a throwaway DB *before* importing it.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

import utils.runtime_config as rc  # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1
    print(f"PASS {label}")


def _write(key, value):
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


def _read(key):
    conn = sqlite3.connect(os.environ["DB_PATH"])
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def test_heals_wrong_urls():
    _write("tempmail_base_url", "https://api.grabmail.io/v1/messages")
    _write("temporasms_base_url", "https://temporasms.com/api")

    repaired = rc.self_heal_base_urls()

    check("tempmail healed", "tempmail_base_url" in repaired, repaired)
    check("temporasms healed", "temporasms_base_url" in repaired, repaired)

    tm = _read("tempmail_base_url")
    ts = _read("temporasms_base_url")
    check("tempmail canonical", tm == "https://grabmail.io/api/v1", tm)
    check("temporasms canonical", ts == "https://api.temporasms.com", ts)

    # Second run must be a no-op (idempotent, one-time).
    again = rc.self_heal_base_urls()
    check("idempotent", again == {}, again)


def test_leaves_correct_values():
    _write("tempmail_base_url", "https://grabmail.io/api/v1")
    _write("temporasms_base_url", "https://api.temporasms.com")
    repaired = rc.self_heal_base_urls()
    check("correct values untouched", repaired == {}, repaired)


def test_ignores_missing_rows():
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("DELETE FROM settings WHERE key IN ('tempmail_base_url','temporasms_base_url')")
    conn.commit()
    conn.close()
    repaired = rc.self_heal_base_urls()
    check("missing rows ignored", repaired == {}, repaired)


def main():
    test_heals_wrong_urls()
    test_leaves_correct_values()
    test_ignores_missing_rows()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            os.unlink(_TMP.name)
        except Exception:
            pass
