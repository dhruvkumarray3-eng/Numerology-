"""Privacy and routing regressions for live admin audit logging."""
import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import database
from utils import audit_logger


class FakeBot:
    def __init__(self, fail_channels=()):
        self.fail_channels = set(fail_channels)
        self.sent = []
        self.handlers = []

    def on(self, event):
        def decorate(handler):
            self.handlers.append(handler)
            return handler
        return decorate

    async def send_message(self, channel, message, **kwargs):
        if channel in self.fail_channels:
            raise RuntimeError("simulated channel failure")
        self.sent.append((channel, message, kwargs))


class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, *_args, **_kwargs):
        return FakeResult(self.row)


def test_audit_log_redacts_payloads_and_continues_after_channel_failure():
    async def run():
        bot = FakeBot(fail_channels={-1001})
        with patch("database.get_log_channels_db", return_value=[-1001, -1002]):
            delivered = await audit_logger.log_admin_action(
                bot,
                actor_id=12345,
                action="button_click",
                details={
                    "command": "/start SECRET_ARGUMENT",
                    "callback": "buy_confirm|PHONE_SECRET|OTP_SECRET",
                    "raw_text": "MESSAGE_SECRET",
                    "otp": "OTP_SECRET",
                },
            )
        assert delivered == 1
        assert len(bot.sent) == 1 and bot.sent[0][0] == -1002
        message = bot.sent[0][1]
        assert "12345" in message
        assert "/start" in message
        assert "buy_confirm" in message
        for secret in ("SECRET_ARGUMENT", "PHONE_SECRET", "OTP_SECRET", "MESSAGE_SECRET"):
            assert secret not in message

    asyncio.run(run())


def test_private_message_and_callback_logs_only_metadata():
    async def run():
        bot = FakeBot()
        audit_logger.register_audit_handlers(bot)
        assert len(bot.handlers) == 2
        with patch("database.get_log_channels_db", return_value=[-1009]):
            await bot.handlers[0](type("Event", (), {
                "is_private": True,
                "sender_id": 77,
                "raw_text": "/deposit PRIVATE_AMOUNT_AND_NOTE",
                "media": None,
            })())
            await bot.handlers[1](type("Event", (), {
                "is_private": True,
                "sender_id": 77,
                "data": b"buy_confirm|PHONE_SECRET|OTP_SECRET",
            })())
            pending = list(audit_logger._TASKS)
            if pending:
                await asyncio.gather(*pending)

        assert len(bot.sent) == 2
        messages = [item[1] for item in bot.sent]
        assert any("/deposit" in message for message in messages)
        assert any("buy_confirm" in message for message in messages)
        joined = "\n".join(messages)
        for secret in ("PRIVATE_AMOUNT_AND_NOTE", "PHONE_SECRET", "OTP_SECRET"):
            assert secret not in joined

    asyncio.run(run())


def test_personal_channel_precedes_and_preserves_configured_channels():
    fake_cur = FakeCursor(("-1002,-1003,-1002",))
    with patch.object(database, "cur", fake_cur), \
         patch.object(config, "ADMIN_LOG_CHANNEL_ID", -1001):
        assert database.get_log_channels_db() == [-1001, -1002, -1003]


def test_generic_activity_is_private_to_personal_channel():
    async def run():
        bot = FakeBot()
        with patch.object(config, "ADMIN_LOG_CHANNEL_ID", -1008), \
             patch("database.get_log_channels_db", return_value=[-1008, -2000]):
            delivered = await audit_logger.log_admin_action(
                bot, actor_id=77, action="message", details={"message_type": "text"}
            )
        assert delivered == 1
        assert [channel for channel, _message, _kwargs in bot.sent] == [-1008]

    asyncio.run(run())


def test_deposit_status_transitions_and_global_registration_are_wired():
    deposit_source = (ROOT / "plugins" / "deposit.py").read_text(encoding="utf-8")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'action="deposit_approved"' in deposit_source
    assert 'action="deposit_custom_amount_approved"' in deposit_source
    assert 'action="deposit_rejected"' in deposit_source
    assert "register_audit_handlers(bot)" in main_source
    assert main_source.index("register_audit_handlers(bot)") < main_source.index("register_all_handlers(bot)")


if __name__ == "__main__":
    tests = [
        test_audit_log_redacts_payloads_and_continues_after_channel_failure,
        test_private_message_and_callback_logs_only_metadata,
        test_personal_channel_precedes_and_preserves_configured_channels,
        test_generic_activity_is_private_to_personal_channel,
        test_deposit_status_transitions_and_global_registration_are_wired,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(tests)} ADMIN AUDIT TESTS PASSED")
