import asyncio
import unittest

from utils import livecount


class FakeBot:
    def __init__(self):
        self.edits = []

    async def edit_message(self, chat_id, msg_id, text, buttons=None):
        self.edits.append((chat_id, msg_id, text, buttons))


class LiveCountCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_unregistered_inflight_render_does_not_edit(self):
        key = "tm:cancel-race@example.test"
        started = asyncio.Event()
        release = asyncio.Event()
        bot = FakeBot()

        async def slow_render():
            started.set()
            await release.wait()
            return "stale inbox", [], False

        original_tick = livecount._TICK
        livecount._REGISTRY.clear()
        livecount._TICK = 0.001
        livecount._REGISTRY[key] = {
            "bot": bot,
            "chat_id": 1,
            "msg_id": 2,
            "render": slow_render,
            "interval": 5.0,
            "next": 0.0,
            "last": None,
            "deadline": None,
            "failures": 0,
        }
        worker = asyncio.create_task(livecount._worker())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            livecount.unregister_live(key)
            release.set()
            await asyncio.sleep(0.02)
            self.assertEqual(bot.edits, [])
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            livecount._REGISTRY.clear()
            livecount._TICK = original_tick


if __name__ == "__main__":
    unittest.main()
