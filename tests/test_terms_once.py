"""Terms gate must never nag the user twice.

Bug: the "Agree & Continue" screen kept coming back in the WhatsApp / TG
Number Change / All Apps OTP / Server-2 panels because acceptance was stored
only in one per-panel ``settings`` row.  Any DB hiccup (read-only file, lock,
ephemeral disk) silently lost it and the user was asked again forever.

Fix locked in here:
1. Accepting stores an in-process flag, so the same process never re-asks.
2. Accepting also sets ``users.terms_accepted``, so it applies to every panel.
3. Accepting is idempotent and always reports success once the flag is set.
4. A broken DB read must not raise.

Run: API_ID=1 API_HASH=x BOT_TOKEN=1:x python3 tests/test_terms_once.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test-hash")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")

from database import cur, db
from plugins import product_panels as PP

CHECKS = []


def check(name, cond, extra=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


UID = 987654321

# clean slate
PP._TC_MEMORY.clear()
cur.execute("DELETE FROM settings WHERE key LIKE ?", (f"pp_tc_{UID}_%",))
cur.execute("UPDATE users SET terms_accepted=0 WHERE user_id=?", (UID,))
db.commit()

check("fresh user is asked", PP._terms_accepted(UID, "whatsapp") is False)
check("accept returns True", PP._accept_terms(UID, "whatsapp") is True)
check("not asked again (same panel)", PP._terms_accepted(UID, "whatsapp") is True)
check("not asked in other panels either",
      PP._terms_accepted(UID, "numchange") and PP._terms_accepted(UID, "allotp")
      and PP._terms_accepted(UID, "nonspam"))

row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (UID,)).fetchone()
check("users.terms_accepted persisted", bool(row and row[0]))

# Simulate a process restart: memory gone, DB must still answer.
PP._TC_MEMORY.clear()
check("survives restart (DB flag)", PP._terms_accepted(UID, "whatsapp") is True)

# Simulate a completely broken DB: must not raise, must not lose memory.
PP._TC_MEMORY.clear()
PP._TC_MEMORY.add((UID, "*"))
real_cur = PP.cur


class _Boom:
    def execute(self, *a, **k):
        raise RuntimeError("database is locked")


PP.cur = _Boom()
try:
    check("broken DB read does not raise", PP._terms_accepted(UID, "whatsapp") is True)
    check("broken DB accept still returns True", PP._accept_terms(UID, "whatsapp") is True)
finally:
    PP.cur = real_cur

failed = [c for c in CHECKS if not c[1]]
print(f"\nPASSED: {len(CHECKS) - len(failed)}  FAILED: {len(failed)}  TOTAL: {len(CHECKS)}")
sys.exit(1 if failed else 0)
