"""Extra admin + user commands for the new feature set.

Admin:
    /setmarkup <percent>          -> profit = percent of panel cost
    /setprofit <amount> <INR|USD> -> profit = fixed amount per sale
    /markup                       -> show current profit configuration
    /history <user_id>            -> full user history (SQLite + MongoDB)
    /mongostatus                  -> MongoDB connection + collection counts
    /panelstats                   -> panel orders, revenue, real cost, profit
    /panelsales [n]               -> last n panel orders
    /panelbalance                 -> TemporaSMS wallet balance
    /grant <user_id> <amount>     -> credit a user's balance
    /resetmarkup                  -> back to defaults (25%)

User:
    /myhistory                    -> own recent orders / deposits / redeems
    /myid                         -> own Telegram id + RDX id
    /support                      -> support link
"""
import html
import datetime

from telethon import events

from config import (
    ADMIN_ID,
    BOT_BRAND_NAME,
    QC_ID_PREFIX,
    format_price,
    logger,
    PE_ID, PE_USER, PE_TAG, PE_STAR, PE_CROWN, PE_CHECK, PE_GIFT,
)
from database import cur, db, ensure_user, is_admin, get_user_currency
from utils.keyboards import style_btn
from utils.markup import (get_markup_config, set_markup, describe_markup,
                          price_breakdown, format_inr, format_usdt)
from utils import mongo_store
from utils import temporasms


def _is_admin(uid):
    try:
        return bool(is_admin(uid)) or bool(ADMIN_ID and uid == ADMIN_ID)
    except Exception:
        return bool(ADMIN_ID and uid == ADMIN_ID)


def _rdx_id(bot_id):
    return f"{QC_ID_PREFIX}-{str(bot_id)[-8:]}" if bot_id else f"{QC_ID_PREFIX}-00000000"


def _fmt_dt(value):
    if isinstance(value, datetime.datetime):
        return value.strftime("%d %b %Y %H:%M")
    if value:
        return str(value)[:16]
    return "—"


def _sqlite_history(uid, limit=15):
    """Best-effort history from the local SQLite database."""
    out = {}
    queries = {
        "orders": "SELECT id, country, year, price, phone, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
        "panel_orders": "SELECT id, panel, country, phone, price, status, date FROM panel_orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
        "deposits": "SELECT id, amount, method_name, status, date FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT ?",
        "redeem_log": "SELECT id, code, amount, date FROM redeem_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
        "smm_orders": "SELECT id, service_name, quantity, price, status, date FROM smm_orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
    }
    for name, sql in queries.items():
        try:
            out[name] = cur.execute(sql, (uid, limit)).fetchall()
        except Exception as exc:
            logger.warning(f"history query {name} failed: {exc}")
            out[name] = []
    return out


async def cmd_setmarkup(e, args):
    if not args:
        return await e.reply("Usage: <code>/setmarkup 25</code>  (percent)")
    try:
        percent = float(args)
    except ValueError:
        return await e.reply("❌ Send a number, e.g. <code>/setmarkup 25</code>")
    set_markup(mode="percent", percent=percent)
    await mongo_store.log_event(e.sender_id, "admin_setmarkup", percent=percent)
    await e.reply(
        "<blockquote expandable>✅ <b>Profit updated</b>\n\n"
        "📈 Mode: <b>percentage</b>\n"
        f"💰 Profit: <b>{percent:g}%</b> of panel cost on every sale\n\n"
        f"<i>Users will see cost + {percent:g}%.</i></blockquote>"
    )


async def cmd_setprofit(e, args):
    if not args:
        return await e.reply(
            "Usage:\n<code>/setprofit 50 INR</code>\n<code>/setprofit 2 USD</code>")
    parts = args.split()
    try:
        amount = float(parts[0])
    except ValueError:
        return await e.reply("❌ First value must be a number, e.g. <code>/setprofit 2 USD</code>")
    currency = (parts[1].upper() if len(parts) > 1 else "INR")
    if currency not in ("INR", "USD"):
        return await e.reply("❌ Currency must be <b>INR</b> or <b>USD</b>.")
    set_markup(mode="fixed", fixed=amount, currency=currency)
    await mongo_store.log_event(e.sender_id, "admin_setprofit",
                                amount=amount, currency=currency)
    await e.reply(
        "<blockquote expandable>✅ <b>Profit updated</b>\n\n"
        "💵 Mode: <b>fixed</b>\n"
        f"💰 Profit: <b>{currency} {amount:g}</b> per sale\n\n"
        "<i>Users will see cost + this fixed amount.</i></blockquote>"
    )


async def cmd_markup(e):
    cfg = get_markup_config()
    await e.reply(
        "<blockquote expandable>⚙️ <b>Current Profit Settings</b>\n\n"
        f"📊 Mode: <b>{cfg['mode']}</b>\n"
        f"📈 Percent: <b>{cfg['percent']:g}%</b>\n"
        f"💵 Fixed: <b>{cfg['currency']} {cfg['fixed']:g}</b>\n\n"
        f"➡️ {describe_markup(cfg)}\n\n"
        f"💱 <b>USDT rate:</b> ₹{price_breakdown(100, cfg)['rate']:g} = 1 USDT\n"
        f"🧾 <b>Example</b> (panel cost ₹100):\n"
        f"   • Cost: ₹100 (hidden from users)\n"
        f"   • Your profit: ₹{price_breakdown(100, cfg)['profit_inr']:,.0f}\n"
        f"   • User pays: {format_inr(price_breakdown(100, cfg)['inr'])} · "
        f"{format_usdt(price_breakdown(100, cfg)['usdt'])}\n\n"
        "<i>Users always see BOTH ₹INR and USDT.\n"
        "Change with /setmarkup 25 or /setprofit 2 USD</i></blockquote>"
    )


async def cmd_history(e, args, bot=None):
    if not args or not args.strip().isdigit():
        return await e.reply("Usage: <code>/history 123456789</code>")
    uid = int(args.strip())
    limit = 10
    sql = _sqlite_history(uid, limit)
    user_row = cur.execute(
        "SELECT balance, total_deposited, joined_date, banned, currency, language "
        "FROM users WHERE user_id=?", (uid,)).fetchone()
    mongo = await mongo_store.get_user_history(uid, limit=50)

    lines = [f"👤 <b>User history — <code>{uid}</code></b>\n"]
    if user_row:
        bal, dep, joined, banned, currency, language = user_row
        lines.append(f"💰 Balance: <b>{format_price(bal or 0, currency or 'INR')}</b>")
        lines.append(f"📥 Total deposited: <b>{format_price(dep or 0, currency or 'INR')}</b>")
        lines.append(f"📅 Joined: <b>{_fmt_dt(joined)}</b>")
        lines.append(f"🌐 Currency: <b>{currency or 'INR'}</b> · 🗣 Language: <b>{language or 'en'}</b>")
        lines.append(f"🚫 Banned: <b>{'Yes' if banned else 'No'}</b>")
    else:
        lines.append("⚠️ No local user record (may exist only in MongoDB).")

    def _section(title, rows, formatter):
        if not rows:
            return
        lines.append(f"\n<b>{title}</b>")
        for row in rows:
            try:
                lines.append("• " + formatter(row))
            except Exception:
                continue

    _section("🧾 TG account orders", sql["orders"],
             lambda r: f"#{r[0]} {r[1]} {r[2]} — ₹{r[3]} · {r[4]} · {_fmt_dt(r[5])}")
    _section("🧩 Panel orders", sql["panel_orders"],
             lambda r: f"#{r[0]} {r[1]} {r[2]} — ₹{r[4]} · {r[5]} · {_fmt_dt(r[6])}")
    _section("💳 Deposits", sql["deposits"],
             lambda r: f"#{r[0]} ₹{r[1]} {r[2]} · {r[3]} · {_fmt_dt(r[4])}")
    _section("🎁 Redeems", sql["redeem_log"],
             lambda r: f"#{r[0]} {r[1]} — ₹{r[2]} · {_fmt_dt(r[3])}")
    _section("🚀 SMM orders", sql["smm_orders"],
             lambda r: f"#{r[0]} {r[1]} x{r[2]} — ₹{r[3]} · {r[4]} · {_fmt_dt(r[5])}")

    if mongo:
        counts = {k: len(v) for k, v in mongo.items() if isinstance(v, list)}
        lines.append("\n<b>🗄 MongoDB</b>")
        lines.append("• " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
        if mongo.get("user"):
            lines.append(f"• Mongo balance: ₹{mongo['user'].get('balance', '—')}")
    elif mongo_store.mongo_enabled():
        lines.append("\n🗄 MongoDB: no records for this user yet.")
    else:
        lines.append("\n🗄 MongoDB: not configured.")

    text = "<blockquote expandable>" + "\n".join(lines) + "</blockquote>"
    if len(text) > 3800:
        text = text[:3800] + "…</blockquote>"
    await e.reply(text)


async def cmd_mongostatus(e):
    line = mongo_store.status_line()
    counts = await mongo_store.collection_counts()
    body = line
    if counts:
        body += "\n\n" + "\n".join(f"• <b>{k}</b>: {v}" for k, v in counts.items())
    else:
        body += "\n\n<i>Set MONGO_URI in your host variables to enable MongoDB storage.</i>"
    await e.reply(f"<blockquote expandable>🗄 <b>MongoDB Status</b>\n\n{body}</blockquote>")


async def cmd_panelstats(e):
    try:
        row = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(price),0), COALESCE(SUM(real_price),0), "
            "COALESCE(SUM(profit),0) FROM panel_orders").fetchone()
        total, revenue, cost, profit = row
        by_panel = cur.execute(
            "SELECT panel, COUNT(*), COALESCE(SUM(price),0), COALESCE(SUM(profit),0) "
            "FROM panel_orders GROUP BY panel").fetchall()
    except Exception as exc:
        return await e.reply(f"⚠️ Could not read panel stats: {exc}")

    lines = [
        "📊 <b>Panel Statistics</b>\n",
        f"🧾 Orders: <b>{total}</b>",
        f"💵 Revenue: <b>₹{revenue:,.0f}</b>",
        f"🏷 Real cost: <b>₹{cost:,.0f}</b>",
        f"📈 Profit: <b>₹{profit:,.0f}</b>",
    ]
    if by_panel:
        lines.append("")
        for panel, cnt, rev, prof in by_panel:
            lines.append(f"• <b>{panel}</b>: {cnt} orders · ₹{rev:,.0f} · profit ₹{prof:,.0f}")
    lines.append(f"\n⚙️ {describe_markup()}")
    await e.reply("<blockquote expandable>" + "\n".join(lines) + "</blockquote>")


async def cmd_panelsales(e, args):
    try:
        n = max(1, min(25, int(args.strip()))) if args and args.strip().isdigit() else 10
    except ValueError:
        n = 10
    rows = cur.execute(
        "SELECT user_id, panel, country, phone, price, status, date FROM panel_orders "
        "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    if not rows:
        return await e.reply("📭 No panel orders yet.")
    lines = [f"🧾 <b>Last {len(rows)} panel orders</b>\n"]
    for uid, panel, country, phone, price, status, date in rows:
        lines.append(f"• <code>{uid}</code> · {panel} · {country} · ₹{price:.0f} · "
                     f"{status} · {_fmt_dt(date)}")
    await e.reply("<blockquote expandable>" + "\n".join(lines) + "</blockquote>")


async def cmd_panelbalance(e):
    result = await temporasms.get_balance()
    if not result.get("ok"):
        return await e.reply(
            "⚠️ <b>TemporaSMS balance unavailable</b>\n\n"
            f"<code>{html.escape(str(result.get('error')))}</code>\n\n"
            "Check <code>TEMPORASMS_API_KEY</code> / <code>TEMPORASMS_BASE_URL</code>.")
    await e.reply(
        "<blockquote expandable>💼 <b>TemporaSMS Wallet</b>\n\n"
        f"💰 Balance: <b>{result['currency']} {result['balance']:,.2f}</b>\n"
        f"🔑 Key: <b>{'configured ✅' if temporasms.configured() else 'missing ❌'}</b></blockquote>"
    )


async def cmd_grant(e, args):
    parts = (args or "").split()
    if len(parts) != 2 or not parts[0].isdigit():
        return await e.reply("Usage: <code>/grant 123456789 100</code>")
    uid, amount = int(parts[0]), float(parts[1])
    ensure_user(uid)
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    db.commit()
    await mongo_store.log_event(e.sender_id, "admin_grant", target=uid, amount=amount)
    await e.reply(f"✅ Credited ₹{amount:,.2f} to <code>{uid}</code>.")


async def cmd_resetmarkup(e):
    set_markup(mode="percent", percent=25, fixed=0, currency="INR")
    await e.reply("✅ Profit reset to <b>25%</b>.")


async def cmd_myhistory(e):
    uid = e.sender_id
    sql = _sqlite_history(uid, 5)
    lines = ["🧾 <b>Your recent activity</b>\n"]
    found = False
    for row in sql["orders"]:
        found = True
        lines.append(f"• TG order #{row[0]} — {row[1]} {row[2]} · ₹{row[3]} · {_fmt_dt(row[5])}")
    for row in sql["panel_orders"]:
        found = True
        lines.append(f"• {row[1]} panel — {row[2]} · ₹{row[4]} · {row[5]} · {_fmt_dt(row[6])}")
    for row in sql["deposits"]:
        found = True
        lines.append(f"• Deposit ₹{row[1]} · {row[3]} · {_fmt_dt(row[4])}")
    for row in sql["redeem_log"]:
        found = True
        lines.append(f"• Redeem {row[1]} — ₹{row[2]} · {_fmt_dt(row[3])}")
    if not found:
        lines.append("<i>No orders yet — your purchases will appear here.</i>")
    await e.reply("<blockquote expandable>" + "\n".join(lines) + "</blockquote>")


async def cmd_myid(e, bot=None):
    uid = e.sender_id
    bot_id = None
    bot_name = BOT_BRAND_NAME or "Store Bot"
    try:
        me = await bot.get_me()
        bot_id = me.id
        bot_name = BOT_BRAND_NAME or me.first_name or bot_name
    except Exception:
        pass
    await e.reply(
        f"<blockquote expandable>{PE_ID} <b>Your IDs</b>\n\n"
        f"{PE_USER} Telegram ID: <code>{uid}</code>\n"
        f"{PE_STAR} Bot: <b>{html.escape(bot_name)}</b>\n"
        f"{PE_TAG} RDX ID: <code>{_rdx_id(bot_id)}</code></blockquote>"
    )


async def cmd_support(e):
    from database import get_support_url
    from config import OWNER_URL, OWNER_USERNAME, SUPPORT_USERNAME
    url = get_support_url()
    await e.reply(
        f"<blockquote expandable>💬 <b>Support</b>\n\n"
        f"👥 <b>Support Group:</b> {SUPPORT_USERNAME}\n"
        f"👑 <b>Owner:</b> {OWNER_USERNAME}\n\n"
        f"👉 <a href='{url}'>{html.escape(url)}</a>\n"
        f"👉 <a href='{OWNER_URL}'>{html.escape(OWNER_URL)}</a></blockquote>"
    )


def register_admin_extras(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/(?:setmarkup|setmargin)(?:@\w+)?(?:\s+(.+))?$"))
    async def h_setmarkup(e):
        if not _is_admin(e.sender_id):
            return
        arg = (e.pattern_match.group(1) or "").strip()
        # /setmargin 25%  -> percent ;  /setmargin 50  -> fixed INR ;  /setmargin 2 USD -> fixed USD
        if arg.endswith("%"):
            await cmd_setmarkup(e, arg[:-1].strip())
        elif len(arg.split()) > 1:
            await cmd_setprofit(e, arg)
        elif arg:
            await cmd_setmarkup(e, arg)
        else:
            await cmd_setmarkup(e, "")

    @bot.on(events.NewMessage(pattern=r"(?i)^/setprofit(?:@\w+)?(?:\s+(.+))?$"))
    async def h_setprofit(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_setprofit(e, (e.pattern_match.group(1) or "").strip())

    @bot.on(events.NewMessage(pattern=r"(?i)^/markup(?:@\w+)?$"))
    async def h_markup(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_markup(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/resetmarkup(?:@\w+)?$"))
    async def h_reset(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_resetmarkup(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/history(?:@\w+)?(?:\s+(.+))?$"))
    async def h_history(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_history(e, (e.pattern_match.group(1) or "").strip(), bot)

    @bot.on(events.NewMessage(pattern=r"(?i)^/mongostatus(?:@\w+)?$"))
    async def h_mongo(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_mongostatus(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/panelstats(?:@\w+)?$"))
    async def h_panelstats(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_panelstats(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/panelsales(?:@\w+)?(?:\s+(.+))?$"))
    async def h_panelsales(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_panelsales(e, (e.pattern_match.group(1) or "").strip())

    @bot.on(events.NewMessage(pattern=r"(?i)^/panelbalance(?:@\w+)?$"))
    async def h_panelbalance(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_panelbalance(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/grant(?:@\w+)?(?:\s+(.+))?$"))
    async def h_grant(e):
        if not _is_admin(e.sender_id):
            return
        await cmd_grant(e, (e.pattern_match.group(1) or "").strip())

    # --- user commands ---------------------------------------------------
    @bot.on(events.NewMessage(pattern=r"(?i)^/myhistory(?:@\w+)?$"))
    async def h_myhistory(e):
        await cmd_myhistory(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/(myid|id)(?:@\w+)?$"))
    async def h_myid(e):
        await cmd_myid(e, bot)

    @bot.on(events.NewMessage(pattern=r"(?i)^/support(?:@\w+)?$"))
    async def h_support(e):
        await cmd_support(e)
