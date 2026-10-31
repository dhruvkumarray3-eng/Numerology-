"""Terms gate must ask once per panel, then never nag again.

Behaviour locked in here (owner requirement):

1. Every product entry point (WhatsApp, TG Number Change, All Apps OTP,
   Good Quality / Cheap TG ...) shows its own "Agree & Continue" screen the
   first time it is opened -- even if the generic /start terms were accepted.
2. Accepting a panel is remembered per panel: the same panel never asks twice
   (in-process memory + a persisted ``pp_tc_<uid>_<key>`` settings row).
3. Accepting one panel does NOT silently accept a different panel.
4. Accepting is idempotent and always reports success once the flag is set.
5. A broken DB read must not raise.

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

# Each panel is independent: accepting WhatsApp must NOT skip Number Change /
# All Apps OTP / the account catalogue.
check("other panels still ask (numchange)", PP._terms_accepted(UID, "numchange") is False)
check("other panels still ask (allotp)", PP._terms_accepted(UID, "allotp") is False)
check("other panels still ask (accounts)", PP._terms_accepted(UID, "accounts") is False)

row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (UID,)).fetchone()
check("users.terms_accepted persisted", bool(row and row[0]))

# Simulate a process restart: memory gone, DB must still answer for the panel
# that was actually accepted.
PP._TC_MEMORY.clear()
check("survives restart (DB flag)", PP._terms_accepted(UID, "whatsapp") is True)
check("still asks other panel after restart", PP._terms_accepted(UID, "numchange") is False)

# Simulate a completely broken DB: must not raise, must not lose memory.
PP._TC_MEMORY.clear()
PP._TC_MEMORY.add((UID, "whatsapp"))
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
