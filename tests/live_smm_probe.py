"""Read-only live probe for the SMM layer + the panel-price/profit display.

Never creates an order.  Prints the exact exception if a handler blows up so
we can fix the bot layer instead of guessing.
"""
import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeMessage:
    def __init__(self):
        self.id = 1
        self.text = ""

    async def edit(self, *a, **kw):
        print("  [edit]", str(a[0])[:120].replace("\n", " | "))
        return self

    async def reply(self, *a, **kw):
        print("  [reply]", str(a[0])[:120].replace("\n", " | "))
        return self

    async def answer(self, *a, **kw):
        print("  [answer]", a, kw)
        return self


class FakeEvent:
    def __init__(self, sender_id=12345):
        self.sender_id = sender_id
        self.message_id = 1
        self.message = FakeMessage()
        self.text = ""

    async def edit(self, *a, **kw):
        return await self.message.edit(*a, **kw)

    async def reply(self, *a, **kw):
        return await self.message.reply(*a, **kw)

    async def respond(self, *a, **kw):
        return await self.message.reply(*a, **kw)

    async def answer(self, *a, **kw):
        return await self.message.answer(*a, **kw)


async def main():
    from utils import smm_client as sc

    for server in (1, 2):
        srv = sc.SMM_SERVERS[server]
        print(f"\n=== server {server}: {srv['url']} ({srv['currency']}) ===")
        services = await sc.fetch_smm_services(server, force_refresh=True)
        print("  services:", len(services))
        if not services:
            continue
        print("  sample keys:", sorted(services[0].keys()))
        plats = await sc.get_smm_platforms(server)
        print("  platforms:", plats)
        if not plats:
            continue
        plat = "Telegram" if "Telegram" in plats else plats[0]
        cats = await sc.get_categories_for_platform(plat, server)
        print(f"  {plat} categories:", len(cats), cats[:2])
        if not cats:
            continue
        svcs = await sc.get_services_for_category(cats[0]["name"], server)
        print(f"  services in '{cats[0]['name']}':", len(svcs))
        if not svcs:
            continue
        s = svcs[0]
        print("  sample service:", {k: s.get(k) for k in ("service", "name", "rate", "min", "max")})
        try:
            print("  breakdown:", sc.get_service_breakdown(s, server))
        except Exception:
            print("  BREAKDOWN FAILED:")
            traceback.print_exc()
        try:
            print("  inr rate:", sc.get_service_inr_rate(s, server))
        except Exception:
            print("  INR RATE FAILED:")
            traceback.print_exc()

    # Now exercise the bot handlers with a stub event.
    print("\n=== handler smoke test ===")
    import plugins.smm as smm

    ev = FakeEvent()
    for label, coro in [
        ("show_smm_servers", smm.show_smm_servers(ev)),
        ("show_smm_platforms_menu(1)", smm.show_smm_platforms_menu(ev, 1)),
        ("show_smm_platforms_menu(2)", smm.show_smm_platforms_menu(ev, 2)),
        ("show_platform_categories(1,Telegram,1)",
         smm.show_platform_categories(ev, 1, "Telegram", 1)),
        ("show_category_services(1,Telegram,0,1)",
         smm.show_category_services(ev, 1, "Telegram", 0, 1)),
    ]:
        print(f"\n-- {label}")
        try:
            await coro
            print("   OK")
        except Exception:
            print("   FAILED:")
            traceback.print_exc()

    # service card needs a real service id
    services = await sc.fetch_smm_services(1)
    if services:
        sid = services[0].get("service")
        print(f"\n-- show_service_card(1, Telegram, 0, {sid})")
        try:
            await smm.show_service_card(ev, 1, "Telegram", 0, sid)
            print("   OK")
        except Exception:
            print("   FAILED:")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
