"""Read-only probe for the admin profit commands (/markup, /panelstats, ...)."""
import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeMsg:
    def __init__(self):
        self.id = 1
        self.text = ""

    async def edit(self, *a, **kw):
        print("  [edit]", str(a[0])[:400].replace("\n", " | "))
        return self

    async def reply(self, *a, **kw):
        print("  [reply]", str(a[0])[:400].replace("\n", " | "))
        return self

    async def answer(self, *a, **kw):
        print("  [answer]", a, kw)
        return self


class FakeEvent:
    def __init__(self, sender_id=1):
        self.sender_id = sender_id
        self.message_id = 1
        self.message = FakeMsg()
        self.text = ""
        self.raw_text = ""

    async def edit(self, *a, **kw):
        return await self.message.edit(*a, **kw)

    async def reply(self, *a, **kw):
        return await self.message.reply(*a, **kw)

    async def respond(self, *a, **kw):
        return await self.message.reply(*a, **kw)

    async def answer(self, *a, **kw):
        return await self.message.answer(*a, **kw)


async def main():
    import plugins.admin_extras as ax
    import database as dbmod

    print("is_admin(1) =", dbmod.is_admin(1))
    ev = FakeEvent(1)

    for label, coro in [
        ("cmd_markup", ax.cmd_markup(ev)),
        ("cmd_panelstats", ax.cmd_panelstats(ev)),
        ("cmd_panelbalance", ax.cmd_panelbalance(ev)),
        ("cmd_setmarkup(25)", ax.cmd_setmarkup(ev, "25")),
        ("cmd_setprofit('50 INR')", ax.cmd_setprofit(ev, "50 INR")),
        ("cmd_resetmarkup", ax.cmd_resetmarkup(ev)),
        ("cmd_markup after", ax.cmd_markup(ev)),
    ]:
        print(f"\n-- {label}")
        try:
            await coro
            print("   OK")
        except Exception:
            print("   FAILED:")
            traceback.print_exc()

    print("\n=== markup engine direct ===")
    from utils import markup
    cfg = markup.get_markup_config()
    print("cfg:", cfg)
    print("describe:", markup.describe_markup(cfg))
    print("apply_markup(100):", markup.apply_markup(100, cfg))
    print("profit_in_inr(100):", markup.profit_in_inr(100, cfg))
    print("price_breakdown(100):", markup.price_breakdown(100, cfg))


if __name__ == "__main__":
    asyncio.run(main())
