import logging
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Keep this provider-unit test independent from the bot's production config.
config_stub = types.ModuleType("config")
config_stub.TEMPORASMS_API_KEY = "test-key"
config_stub.TEMPORASMS_BASE_URL = "https://example.invalid"
config_stub.logger = logging.getLogger("temporasms-test")
sys.modules["config"] = config_stub

from utils import temporasms


class TemporaSmsCancelTests(unittest.IsolatedAsyncioTestCase):
    async def _cancel_with_response(self, response, error=None):
        async def fake_call(action, **params):
            self.assertEqual(action, "setStatus")
            self.assertEqual(params, {"id": "order-1", "status": "8"})
            return response, error

        original = temporasms._call
        temporasms._call = fake_call
        try:
            return await temporasms.cancel("order-1")
        finally:
            temporasms._call = original

    async def test_recognizes_provider_cancel_acknowledgments(self):
        for response in (
            "ACCESS_CANCEL",
            "STATUS_CANCEL",
            '{"ok": true, "status": "cancelled"}',
        ):
            with self.subTest(response=response):
                result = await self._cancel_with_response(response)
                self.assertTrue(result["ok"])
                self.assertIsNone(result["error"])

    async def test_does_not_treat_provider_error_as_cancel_success(self):
        for response in (
            "BAD_STATUS",
            "NO_ACTIVATION",
            "STATUS_OK",
            "ERROR_SQL",
            '{"ok": false, "status": "cancelled"}',
        ):
            with self.subTest(response=response):
                result = await self._cancel_with_response(response)
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"])

    async def test_network_error_is_not_cancel_success(self):
        result = await self._cancel_with_response(None, "connection failed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "connection failed")


if __name__ == "__main__":
    unittest.main()
