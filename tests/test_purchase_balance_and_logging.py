"""Regression tests for All Apps purchase billing and sale logging."""
import asyncio
import os
import pathlib
import sys
import types
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test")
os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_ID", "1")

from plugins import all_apps as aa  # noqa: E402
from utils import purchase_logging  # noqa: E402


class FakeCursor:
    def __init__(self, balance):
        self.balance = float(balance)
        self.rowcount = 0
        self._fetch = None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("update users set balance = balance -"):
            amount, user_id, minimum = params
            self.rowcount = int(user_id == 7 and self.balance >= float(minimum))
            if self.rowcount:
                self.balance -= float(amount)
        elif normalized.startswith("update users set balance = balance +"):
            amount, user_id = params
            self.rowcount = int(user_id == 7)
            if self.rowcount:
                self.balance += float(amount)
        elif normalized.startswith("select balance from users"):
            self._fetch = (self.balance,)
            self.rowcount = -1
        else:
            raise AssertionError(f"Unexpected SQL in purchase test: {sql}")
        return self

    def fetchone(self):
        return self._fetch


class FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeClient:
    def __init__(self):
        self.messages = []

    async def send_message(self, channel, message, **kwargs):
        self.messages.append((channel, message, kwargs))


class FakeEvent:
    sender_id = 7

    def __init__(self):
        self.client = FakeClient()
        self.answers = []
        self.edits = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))

    async def edit(self, text, **kwargs):
        self.edits.append((text, kwargs))


def run_purchase(initial_balance, provider_result):
    cursor = FakeCursor(initial_balance)
    db = FakeDB()
    event = FakeEvent()
    provider_calls = []
    stored_orders = []
    mongo_logs = AsyncMock(return_value=True)
    channel_logs = AsyncMock(return_value=1)

    async def get_stock(app, country):
        return 9, 8.0, "temporasms"

    async def buy_number(app, country):
        provider_calls.append((app, country))
        if isinstance(provider_result, Exception):
            raise provider_result
        return provider_result

    fake_panels = types.ModuleType("plugins.product_panels")
    fake_panels._create_order = lambda *args: stored_orders.append(args)
    old_panels = sys.modules.get("plugins.product_panels")
    sys.modules["plugins.product_panels"] = fake_panels

    saved = {
        "cur": aa.cur,
        "db": aa.db,
        "ensure_user": aa.ensure_user,
        "provider_configured": aa.provider_configured,
        "get_stock": aa.get_stock,
        "buy_number": aa.buy_number,
        "apply_service_markup": aa.apply_service_markup,
        "mongo_log": aa.mongo_store.log_panel_order,
        "notify": aa.notify_purchase_channels,
    }
    aa.cur = cursor
    aa.db = db
    aa.ensure_user = lambda _uid: None
    aa.provider_configured = lambda: True
    aa.get_stock = get_stock
    aa.buy_number = buy_number
    aa.apply_service_markup = lambda _cost, _service: 10.0
    aa.mongo_store.log_panel_order = mongo_logs
    aa.notify_purchase_channels = channel_logs
    aa.otp_state.pop(7, None)
    try:
        asyncio.run(aa.do_buy(event, "whatsapp", "in"))
    finally:
        aa.cur = saved["cur"]
        aa.db = saved["db"]
        aa.ensure_user = saved["ensure_user"]
        aa.provider_configured = saved["provider_configured"]
        aa.get_stock = saved["get_stock"]
        aa.buy_number = saved["buy_number"]
        aa.apply_service_markup = saved["apply_service_markup"]
        aa.mongo_store.log_panel_order = saved["mongo_log"]
        aa.notify_purchase_channels = saved["notify"]
        if old_panels is None:
            sys.modules.pop("plugins.product_panels", None)
        else:
            sys.modules["plugins.product_panels"] = old_panels
    return cursor, event, provider_calls, stored_orders, mongo_logs, channel_logs


def test_zero_balance_never_calls_provider():
    cursor, event, calls, orders, mongo, channel = run_purchase(0, {"ok": True})
    assert cursor.balance == 0
    assert calls == [], "provider must not be called without sufficient balance"
    assert not orders and not mongo.await_args_list and not channel.await_args_list
    assert event.answers and "Insufficient balance" in event.answers[0][0]


def test_provider_failure_refunds_reserved_balance():
    cursor, event, calls, orders, mongo, channel = run_purchase(
        20, {"ok": False, "error": "no stock"}
    )
    assert cursor.balance == 20
    assert calls == [("whatsapp", "in")]
    assert not orders and not mongo.await_args_list and not channel.await_args_list
    assert event.edits and "returned to your balance" in event.edits[0][0]


def test_success_debits_and_records_order_and_log():
    result = {
        "ok": True,
        "phone": "+919876543210",
        "order_id": "otp-123",
        "provider": "temporasms",
    }
    cursor, event, calls, orders, mongo, channel = run_purchase(20, result)
    assert cursor.balance == 10
    assert calls == [("whatsapp", "in")]
    assert len(orders) == 1 and orders[0][0:2] == (7, "allapps:whatsapp")
    assert mongo.await_args.kwargs["order_id"] == "otp-123"
    assert "WhatsApp OTP" in channel.await_args.kwargs["product"]
    assert event.edits and "Paid" in event.edits[0][0]


def test_purchase_logger_continues_after_channel_failure_and_masks_phone():
    client = FakeClient()

    async def send_message(channel_id, message, **kwargs):
        if channel_id == -1001:
            raise RuntimeError("channel unavailable")
        client.messages.append((channel_id, message, kwargs))

    client.send_message = send_message
    with patch("database.get_log_channels_db", return_value=[-1001, -1002]):
        delivered = asyncio.run(purchase_logging.notify_purchase_channels(
            client,
            user_id=7,
            product="Amazon <OTP>",
            country="IN",
            phone="+919876543210",
            price=10,
            order_id="otp-123",
            provider="temporasms",
        ))
    assert delivered == 1
    assert len(client.messages) == 1 and client.messages[0][0] == -1002
    logged = client.messages[0][1]
    assert "Amazon &lt;OTP&gt;" in logged
    assert "••••3210" in logged
    assert "+919876543210" not in logged


def test_product_panel_debit_is_conditional_and_before_provider_call():
    source = (ROOT / "plugins" / "product_panels.py").read_text(encoding="utf-8")
    debit = source.index("UPDATE users SET balance = balance - ?")
    provider = source.index("temporasms.buy_number(_service_for(key, uid), code)")
    assert "WHERE user_id = ? AND balance >= ?" in source[debit:debit + 180]
    assert debit < provider
    assert "UPDATE users SET balance = balance + ? WHERE user_id = ?" in source[provider:provider + 700]


def test_manual_and_smm_purchase_debits_are_checked():
    manual = (ROOT / "utils" / "manual_stock.py").read_text(encoding="utf-8")
    manual_debit = manual.index("UPDATE users SET balance = balance - ?")
    assert "WHERE user_id=? AND balance >= ?" in manual[manual_debit:manual_debit + 180]
    assert "if charged.rowcount != 1" in manual[manual_debit:manual_debit + 500]

    smm = (ROOT / "plugins" / "smm.py").read_text(encoding="utf-8")
    smm_debit = smm.index("UPDATE users SET balance = balance - ?")
    provider = smm.index("create_smm_order(service_id, link, qty, server)")
    assert "if cur.rowcount != 1" in smm[smm_debit:provider]
    assert smm_debit < provider


if __name__ == "__main__":
    tests = [
        test_zero_balance_never_calls_provider,
        test_provider_failure_refunds_reserved_balance,
        test_success_debits_and_records_order_and_log,
        test_purchase_logger_continues_after_channel_failure_and_masks_phone,
        test_product_panel_debit_is_conditional_and_before_provider_call,
        test_manual_and_smm_purchase_debits_are_checked,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(tests)} PURCHASE SAFETY TESTS PASSED")
