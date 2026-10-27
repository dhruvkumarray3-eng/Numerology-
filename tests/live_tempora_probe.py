"""Read-only live probe of the TemporaSMS panel (never buys a number).

Verifies the protocol the bot must speak:

  * ``operator`` is a *required* parameter for getCountries / getServices /
    getPrices* -- without it the panel answers ``BAD_OPERATOR``.
  * service codes are per-operator: ``tvm`` = telegram and ``wqp`` = whatsapp
    only exist in operator 13's catalogue, so the client must resolve the
    code *and* the operator before asking for prices.
  * ``getPricesV3`` needs ``service`` + ``country`` + ``operator``; there is
    no "all countries" call, so a country sweep is required.

Usage:
    TEMPORASMS_API_KEY='...' python3 tests/live_tempora_probe.py [service]
"""
import asyncio
import json
import os
import sys

import aiohttp

BASE = "https://api.temporasms.com/stubs/handler_api.php"
KEY = os.getenv("TEMPORASMS_API_KEY", "").strip()
OPERATORS = [1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15, 16]


async def call(session, **params):
    params["api_key"] = KEY
    async with session.get(BASE, params=params, timeout=40) as r:
        return (await r.text()).strip()


async def main():
    if not KEY:
        print("TEMPORASMS_API_KEY not set")
        return 1
    service = (sys.argv[1] if len(sys.argv) > 1 else "telegram").lower()

    async with aiohttp.ClientSession() as s:
        print("balance:", await call(s, action="getBalance"))

        # 1. which operator sells the service?
        found = None
        for op in OPERATORS:
            txt = await call(s, action="getServices", country=0, operator=op)
            try:
                data = json.loads(txt)
            except Exception:
                continue
            hits = [(k, v) for k, v in data.items()
                    if service in str(v).lower()]
            print(f"  operator {op}: {len(data)} services, "
                  f"{len(hits)} matching {service!r} -> {hits[:3]}")
            if hits and found is None:
                found = (op, hits[0][0], hits[0][1])
        if not found:
            print(f"!! no operator sells {service!r}")
            return 1
        op, code, name = found
        print(f"\nresolved: service={code} ({name}) operator={op}")

        # 2. country catalogue for that operator
        countries = json.loads(await call(s, action="getCountries", operator=op))
        print(f"countries for operator {op}: {len(countries)}")

        # 3. sweep prices for the service
        sem = asyncio.Semaphore(15)

        async def one(cid):
            async with sem:
                txt = await call(s, action="getPricesV3", service=code,
                                 country=cid, operator=op)
            try:
                data = json.loads(txt)
            except Exception:
                return cid, None
            node = (data.get(str(cid)) or {}).get(code) or {}
            return cid, node

        rows = await asyncio.gather(*(one(c) for c in countries))
        live = []
        for cid, node in rows:
            if not node:
                continue
            count = int(node.get("count") or 0)
            price = node.get("price")
            if count > 0:
                live.append((countries[cid], cid, price, count))
        live.sort(key=lambda r: r[2] or 0)
        print(f"\ncountries with stock: {len(live)}")
        for name_, cid, price, count in live[:15]:
            print(f"  {cid:>4} {name_:<28} price={price} stock={count}")
        if not live:
            print("  (no stock anywhere right now)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
