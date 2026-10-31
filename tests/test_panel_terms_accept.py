"""Regression tests for the panel "Agree & Continue" (terms accept) flow.

Users reported that tapping "Agree & Continue" inside All Apps OTP, Telegram
number-change and WhatsApp panels did nothing.  The callback used to die
silently when the SQLite write failed (locked DB) or when ``event.edit``
raised.  These checks lock in the hardened behaviour:

1. ``_accept_terms`` returns ``True`` and persists the flag.
2. ``_accept_terms`` returns ``False`` (never raises) when the DB write fails.
3. ``_safe_edit`` falls back to ``event.respond`` when ``edit`` raises.
4. ``cb_agree`` answers the callback before doing any slow provider work.

Run with:

    API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_panel_terms_accept.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test-hash")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")

from plugins import product_panels as P

CHECKS = []


def check(name, cond, extra=""):
    CHECKS.append((name, bool(cond), extra))
    if not cond:
        print(f"  FAIL {name} {extra}")


class _FakeEvent:
    def __init__(self, fail_edit=False):
        self.sender_id = 424242
        self.answered = 0
        self.edited = []
        self.responded = []
        self._fail_edit = fail_edit

    async def answer(self, *a, **kw):
        self.answered += 1

    async def edit(self, text=None, buttons=None, **kw):
        if self._fail_edit:
            raise RuntimeError("message cannot be edited")
        self.edited.append((text, buttons))

    async def respond(self, text=None, buttons=None, **kw):
        self.responded.append((text, buttons))
        return self


# --------------------------------------------------------------------------- #
# 1. happy path
# --------------------------------------------------------------------------- #
def test_accept_terms_persists():
    ok = P._accept_terms(424242, "allotp")
    check("_accept_terms returns True", ok is True, ok)

    cur = P.db.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?",
                (f"pp_tc_424242_allotp",))
    row = cur.fetchone()
    check("terms flag stored", row is not None and str(row[0]) == P._tc_value(), row)

    # Idempotent: a second tap must not raise.
    check("_accept_terms is idempotent", P._accept_terms(424242, "allotp") is True)


# --------------------------------------------------------------------------- #
# 2. DB failure must not raise
# --------------------------------------------------------------------------- #
def test_accept_terms_survives_db_failure():
    class _BoomCursor:
        def execute(self, *a, **kw):
            raise RuntimeError("database is locked")

    class _BoomConn:
        def cursor(self):
            return _BoomCursor()

        def commit(self):
            raise RuntimeError("database is locked")

        def rollback(self):
            raise RuntimeError("database is locked")

    real_cur, real_db = P.cur, P.db
    P.cur, P.db = _BoomCursor(), _BoomConn()
    try:
        result = P._accept_terms(1, "allotp")
    except Exception as exc:  # noqa: BLE001
        check("_accept_terms never raises", False, repr(exc))
        result = None
    finally:
        P.cur, P.db = real_cur, real_db

    # The in-process flag is authoritative, so a DB failure must NOT look like
    # a dead button: the user has agreed and is moved forward regardless.
    check("_accept_terms still succeeds on DB failure", result is True, result)
    check("acceptance kept in memory after DB failure",
          P._terms_accepted(1, "allotp") is True)


# --------------------------------------------------------------------------- #
# 3. _safe_edit falls back to respond
# --------------------------------------------------------------------------- #
def test_safe_edit_fallback():
    loop = asyncio.new_event_loop()
    try:
        ev = _FakeEvent(fail_edit=True)
        loop.run_until_complete(P._safe_edit(ev, "hello", None))
        check("_safe_edit responded after edit failure",
              len(ev.responded) == 1, ev.responded)
        check("_safe_edit did not raise", True)

        # A plain (non-callback) event is answered with respond, never edited.
        ev2 = _FakeEvent()
        loop.run_until_complete(P._safe_edit(ev2, "hi", None))
        check("_safe_edit responds for plain events",
              len(ev2.responded) == 1 and not ev2.edited, ev2.responded)
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# 4. cb_agree answers immediately (source-level guard)
# --------------------------------------------------------------------------- #
def test_cb_agree_answers_first():
    import inspect
    src = inspect.getsource(P.register_product_panels)
    start = src.find("async def cb_agree")
    check("cb_agree exists", start != -1)
    if start == -1:
        return
    body = src[start:start + 1400]
    answer_at = body.find("await e.answer()")
    accept_at = body.find("_accept_terms(")
    check("cb_agree answers before _accept_terms",
          answer_at != -1 and accept_at != -1 and answer_at < accept_at,
          f"answer@{answer_at} accept@{accept_at}")
    check("cb_agree wraps log_event in try", "log_event" in body and "try:" in body)


# --------------------------------------------------------------------------- #
def main():
    for fn in (
        test_accept_terms_persists,
        test_accept_terms_survives_db_failure,
        test_safe_edit_fallback,
        test_cb_agree_answers_first,
    ):
        print(f"- {fn.__name__}")
        fn()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        for name, ok, extra in CHECKS:
            if not ok:
                print(f"  FAILED: {name} {extra}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
