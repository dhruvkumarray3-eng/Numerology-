"""Regression tests for the "Cannot operate on a closed database" bug.

The bug had two halves:

1. ``config.py`` defined a module-level ``cur`` bound to a connection it then
   closed.  ``plugins/admin_actions.py`` does ``from database import cur`` and
   later ``from config import *``, so the *dead* cursor silently replaced the
   live one and every UPI / Auto-UPI / IMAP admin screen crashed.
2. Nothing could recover once a connection was closed, so a single stray
   ``close()`` permanently broke the bot until a restart.

These tests pin both behaviours down.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
import config  # noqa: E402

checks = 0


def check(label, condition):
    global checks
    assert condition, f"FAILED: {label}"
    checks += 1
    print(f"  ok  {label}")


# ---------------------------------------------------------------------------
# 1. config must never export a public `cur` / `conn`
# ---------------------------------------------------------------------------
print("\n[1] config star-import cannot shadow the database cursor")
check("config has no public 'cur'", not hasattr(config, "cur"))
check("config has no public 'conn'", not hasattr(config, "conn"))

ns = {}
exec("from config import *", ns)
check("'cur' not exported by from config import *", "cur" not in ns)
check("'db' not exported by from config import *", "db" not in ns)

# The real scenario: database's cursor imported first, then config's star import.
live_cursor = database.cur
ns2 = {"cur": live_cursor}
exec("from config import *", ns2)
check("star-import leaves the live cursor untouched", ns2["cur"] is live_cursor)


# ---------------------------------------------------------------------------
# 2. the proxies survive a closed connection
# ---------------------------------------------------------------------------
print("\n[2] database proxies self-heal after a close")
database.cur.execute("SELECT 1").fetchone()

raw = database._raw_db
try:
    raw.close()
except Exception:
    pass

row = database.cur.execute("SELECT 1").fetchone()
check("cur still works after raw connection was closed", row == (1,))

database.db.execute("SELECT 1").fetchone()
check("db proxy still works after close", True)

# A write must work too (this is what the admin panel does).
database.cur.execute(
    "CREATE TABLE IF NOT EXISTS _resilience_probe (k TEXT PRIMARY KEY, v TEXT)"
)
database.cur.execute(
    "INSERT OR REPLACE INTO _resilience_probe (k, v) VALUES ('probe', 'yes')"
)
database.db.commit()
got = database.cur.execute(
    "SELECT v FROM _resilience_probe WHERE k='probe'"
).fetchone()
check("write + read survive a closed connection", got == ("yes",))
database.cur.execute("DROP TABLE IF EXISTS _resilience_probe")
database.db.commit()


# ---------------------------------------------------------------------------
# 3. settings round-trip (the UPI / IMAP keys the admin panel edits)
# ---------------------------------------------------------------------------
print("\n[3] settings round-trip for UPI / Auto-UPI / IMAP keys")
for key, value in (
    ("upi_id", "test-user@fam"),
    ("gmail_user", "tester@gmail.com"),
    ("gmail_pass", "abcd efgh ijkl mnop"),
    ("deposit_mode", "hybrid"),
):
    database.cur.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
database.db.commit()

from utils import runtime_config  # noqa: E402
from utils.imap_verifier import get_imap_credentials, imap_status  # noqa: E402

check("upi_id readable", database.get_upi_id() == "test-user@fam")
check("runtime_config sees the same DB file",
      os.path.abspath(runtime_config._db_path()) == os.path.abspath(database.db_path))
check("runtime_config.get('upi_id')", runtime_config.get("upi_id") == "test-user@fam")

user, pwd = get_imap_credentials()
check("IMAP user resolved", user == "tester@gmail.com")
check("IMAP password resolved", pwd == "abcd efgh ijkl mnop")
check("imap_status().configured", imap_status()["configured"] is True)

# A closed DB must not make credentials look missing.
try:
    database._raw_db.close()
except Exception:
    pass
user2, pwd2 = get_imap_credentials()
check("IMAP credentials survive a closed DB", (user2, pwd2) == (user, pwd))


# ---------------------------------------------------------------------------
# 4. admin_actions really uses the live cursor
# ---------------------------------------------------------------------------
print("\n[4] admin_actions module-level cursor is the live proxy")
import plugins.admin_actions as aa  # noqa: E402

check("admin_actions.cur is database.cur", aa.cur is database.cur)
check("admin_actions.cur is not a dead cursor",
      aa.cur.execute("SELECT 1").fetchone() == (1,))
check("admin_actions.db is database.db", aa.db is database.db)

print(f"\n=== ALL {checks} CHECKS PASSED ===")
