import importlib.util
import logging
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeCursor:
    def __init__(self):
        self.inboxes = set()
        self._one = None
        self._all = []
        self.deleted = []

    def execute(self, query, params=()):
        if query.startswith("SELECT 1 FROM tempmail_inboxes"):
            self._one = (1,) if tuple(params) in self.inboxes else None
        elif query.startswith("SELECT email FROM tempmail_inboxes"):
            uid = params[0]
            self._all = [(email,) for owner, email in self.inboxes if owner == uid]
        elif query.startswith("DELETE FROM tempmail_inboxes"):
            uid, email = params
            self.deleted.append((uid, email))
            self.inboxes.discard((uid, email))
        return self

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class FakeEvent:
    def __init__(self, uid):
        self.sender_id = uid
        self.chat_id = uid
        self.message_id = 1
        self.answers = []
        self.edits = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))

    async def edit(self, text, buttons=None):
        self.edits.append((text, buttons))
        return self


cursor = FakeCursor()
db_stub = types.ModuleType("database")
db_stub.cur = cursor
db_stub.db = types.SimpleNamespace(commit=lambda: None)
sys.modules["database"] = db_stub

config_stub = types.ModuleType("config")
config_stub.logger = logging.getLogger("tempmail-cancel-test")
config_stub.PE_CHECK = "✓"
config_stub.PE_LIGHTNING = "⚡"
config_stub.PE_GIFT = "🎁"
sys.modules["config"] = config_stub

keyboards_stub = types.ModuleType("utils.keyboards")
keyboards_stub.style_btn = lambda *args, **kwargs: (args, kwargs)
sys.modules["utils.keyboards"] = keyboards_stub

livecount_stub = types.ModuleType("utils.livecount")
livecount_stub.unregistered = []
livecount_stub.register_live = lambda *args, **kwargs: None
livecount_stub.unregister_live = lambda key: livecount_stub.unregistered.append(key)
sys.modules["utils.livecount"] = livecount_stub

tm_stub = types.ModuleType("utils.tempmail")
tm_stub.TempMailError = type("TempMailError", (Exception,), {})
tm_stub.extract_otp = lambda text: None
sys.modules["utils.tempmail"] = tm_stub

spec = importlib.util.spec_from_file_location("tempmail_plugin_under_test", ROOT / "plugins" / "tempmail.py")
tempmail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tempmail)
tempmail.events = types.SimpleNamespace(CallbackQuery=types.SimpleNamespace(Event=FakeEvent))


class TempMailCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cursor.inboxes.clear()
        cursor.deleted.clear()
        livecount_stub.unregistered.clear()
        tempmail._tm_state.clear()

    async def test_cancel_removes_owned_inbox_and_stops_live_refresh(self):
        uid, email = 123, "owner@example.test"
        cursor.inboxes.add((uid, email))
        tempmail._tm_state[uid] = {"email": email}
        event = FakeEvent(uid)

        await tempmail.cancel_mail(event, email)

        self.assertNotIn((uid, email), cursor.inboxes)
        self.assertEqual(cursor.deleted, [(uid, email)])
        self.assertEqual(livecount_stub.unregistered, [f"tm:{uid}:{email}"])
        self.assertNotIn(uid, tempmail._tm_state)
        self.assertIn("Mailbox cancelled", event.answers[0][0])
        self.assertIn("FREE TEMP MAIL", event.edits[-1][0])

    async def test_cannot_cancel_another_users_mailbox(self):
        owner_email = "owner@example.test"
        other_email = "other@example.test"
        cursor.inboxes.add((123, owner_email))
        tempmail._tm_state[123] = {"email": owner_email}
        event = FakeEvent(123)

        await tempmail.cancel_mail(event, other_email)

        self.assertEqual(cursor.inboxes, {(123, owner_email)})
        self.assertEqual(cursor.deleted, [])
        self.assertEqual(livecount_stub.unregistered, [])
        self.assertEqual(tempmail._tm_state[123]["email"], owner_email)
        self.assertIn("not found", event.answers[0][0].lower())


if __name__ == "__main__":
    unittest.main()
