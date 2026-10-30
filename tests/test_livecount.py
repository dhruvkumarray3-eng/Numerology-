import asyncio, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.livecount import register_live, unregister_live, is_live


class FakeBot:
    def __init__(self):
        self.edits = []

    async def edit_message(self, chat_id, msg_id, text, buttons=None):
        self.edits.append((time.time(), text))


def countdown(expires):
    left = int(expires - time.time())
    if left <= 0:
        return "00:00", True
    return f"{left // 60:02d}:{left % 60:02d}", False


async def main():
    bot = FakeBot()
    expires = time.time() + 20  # 20s mailbox

    async def render():
        left, expired = countdown(expires)
        return f"Time Remaining: {left}", [[("btn", "x")]], expired

    register_live("test:1", bot, 111, 222, render, interval=4.0)
    assert is_live("test:1"), "not registered"

    # run ~14s -> should produce ~3 edits with DIFFERENT countdown values
    await asyncio.sleep(14)

    print(f"edits made: {len(bot.edits)}")
    for ts, text in bot.edits:
        print("  ", text)

    values = [t.split(": ")[1] for _, t in bot.edits]
    assert len(bot.edits) >= 2, f"expected >=2 auto edits, got {len(bot.edits)}"
    assert len(set(values)) == len(values), f"countdown did not change: {values}"
    print("\nPASS: countdown auto-ticks and each edit has a new value")

    unregister_live("test:1")
    assert not is_live("test:1")
    print("PASS: unregister works")


asyncio.run(main())
