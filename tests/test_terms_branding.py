import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "terms-brand-test")
os.environ.setdefault("BOT_TOKEN", "123:terms-test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.terms import get_terms_message


def main():
    message = get_terms_message()
    assert message is not None
    assert "Vendor Sellings by verified owner @Vendor_masterz" in message
    assert "Selfish Otp Bot Ares THE GOD OF WAR" not in message
    print("PASS: Read Terms shows the requested Vendor Sellings heading")


if __name__ == "__main__":
    main()
