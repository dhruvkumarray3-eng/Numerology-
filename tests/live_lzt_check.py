"""Live LZT API verification (read-only).

Run:
    LZT_API_KEY='...' python3 tests/live_lzt_check.py

This script only performs READ operations:
  * GET /me                 -> account, balance, scopes
  * GET /telegram           -> category search (stock)
  * GET /telegram?country[] -> per-country stock counts
It never calls fast-buy, so no money is spent.
"""
import asyncio
import json
import os
import sys

import aiohttp

BASE = "https://api.lzt.market"
KEY = os.environ.get("LZT_API_KEY", "").strip()


def mask(s):
    if not s:
        return "<empty>"
    return f"{s[:12]}...{s[-6:]} (len={len(s)})"


async def get(session, path, params=None):
    url = BASE + path
    headers = {"Authorization": f"Bearer {KEY}", "Accept": "application/json"}
    async with session.get(url, headers=headers, params=params or {}) as r:
        body = await r.text()
        try:
            data = json.loads(body)
        except Exception:
            data = None
        return r.status, data, body


async def main():
    if not KEY:
        print("LZT_API_KEY env var missing")
        return 1
    print(f"key: {mask(KEY)}")

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        # 1) /me
        st, data, body = await get(s, "/me")
        print(f"\n[1] GET /me -> {st}")
        if st == 200 and isinstance(data, dict):
            u = data.get("user", data)
            print("    username :", u.get("username"))
            print("    user_id  :", u.get("user_id"))
            print("    balance  :", u.get("balance"))
            print("    currency :", u.get("balance_currency") or u.get("currency"))
            print("    sympathies:", u.get("sympathies"))
            print("    scopes   :", u.get("scopes") or u.get("scope"))
            print("    keys     :", sorted(u.keys())[:25])
            bal = data.get("balance") or u.get("balance")
            print("    >>> usable balance:", bal)
        else:
            print("    body:", body[:500])

        # 2) global telegram stock
        st, data, body = await get(s, "/telegram", {"page": 1})
        print(f"\n[2] GET /telegram -> {st}")
        if st == 200 and isinstance(data, dict):
            items = data.get("items") or []
            print("    totalItems:", data.get("totalItems"))
            print("    items on page:", len(items))
            for it in items[:5]:
                print(
                    "     -",
                    it.get("item_id"),
                    "|",
                    it.get("title", "")[:40],
                    "| price:",
                    it.get("price"),
                    "| rub:",
                    it.get("rub_price"),
                    "| country:",
                    it.get("telegram_country"),
                    "| spam:",
                    it.get("telegram_spam_block"),
                )
        else:
            print("    body:", body[:500])

        # 3) per-country counts
        countries = ["India", "United States", "Russia", "Bangladesh", "Nigeria"]
        print("\n[3] per-country stock")
        for c in countries:
            st, data, body = await get(s, "/telegram", {"country[]": c, "page": 1})
            if st == 200 and isinstance(data, dict):
                print(f"    {c:<15} total={data.get('totalItems')} page_items={len(data.get('items') or [])}")
            else:
                print(f"    {c:<15} HTTP {st} {body[:160]}")
            await asyncio.sleep(3)

        # 4) check balance endpoint used by the bot
        st, data, body = await get(s, "/user/payments")
        print(f"\n[4] GET /user/payments -> {st}")
        if st == 200 and isinstance(data, dict):
            pays = data.get("payments") or []
            print("    payments:", len(pays))
            for p in pays[:5]:
                print("     -", p.get("payment_id"), p.get("operation"), p.get("amount"), p.get("currency"))
        else:
            print("    body:", body[:300])

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
