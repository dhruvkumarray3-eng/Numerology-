import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "smm-display-test")
os.environ.setdefault("BOT_TOKEN", "123:display-test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugins.smm as smm
from utils.smm_client import SMM_SERVERS


class FakeEvent:
    def __init__(self):
        self.text = None
        self.buttons = None

    async def edit(self, text, buttons=None):
        self.text = text
        self.buttons = buttons

    async def answer(self, text, **_kwargs):
        self.text = text


async def _service_details(_service_id, _server):
    return {
        "service": 2116,
        "name": "Instagram followers",
        "rate": 193.56,
        "min": 500,
        "max": 80000,
    }


def test_combined_customer_price_and_vip_label():
    original_details = smm.get_smm_service_details
    original_price = smm.get_service_inr_rate
    try:
        smm.get_smm_service_details = _service_details
        # The mocked value represents provider rate plus configured markup.
        smm.get_service_inr_rate = lambda _service, _server: 242.0
        event = FakeEvent()
        asyncio.run(smm.show_service_card(event, 1, "Instagram", 0, 2116))

        assert "₹242.0/1k" in event.text
        assert "Panel Rate" not in event.text
        assert "Your Profit" not in event.text
        assert "owner profit" not in event.text.lower()
        assert "Your Price" not in event.text

        vip = "".join(chr(codepoint) for codepoint in (0x1D5E9, 0x1D5DC, 0x1D5E3))
        vil = "".join(chr(codepoint) for codepoint in (0x1D5E9, 0x1D5DC, 0x1D5DF))
        assert SMM_SERVERS[1]["name"].startswith(vip)
        assert not SMM_SERVERS[1]["name"].startswith(vil)
        print("PASS: SMM customers see only the combined rate and the server label reads VIP")
    finally:
        smm.get_smm_service_details = original_details
        smm.get_service_inr_rate = original_price


if __name__ == "__main__":
    test_combined_customer_price_and_vip_label()
