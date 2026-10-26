"""Manual "Basic Telegram Account" stock panel.

User side
---------
A dedicated, flag-rich catalogue of hand-added Telegram accounts.  Users pick
a country, see the available accounts with their price, confirm and buy.  The
account credentials (phone / session / 2FA) are delivered instantly and the
balance is deducted atomically.

Admin side
----------
  /addtg            interactive wizard (country -> phone -> price -> 2FA -> session)
  /addtg C | phone | price | 2fa | session      one-line add
  /listtg           list available manual accounts
  /deltg <id>       delete one account
  /cleartg          wipe the manual pool (with confirmation)
  /tgstats          manual stock summary
  /clearoldstock    wipe the OLD auto-imported `stock` table + price cache
"""

from __future__ import annotations

import html
import time

from telethon import events

from config import bot, format_price, logger, PE_ID, PE_PHONE, PE_CARD, PE_CHECK, PE_GIFT
from database import (
    cur, db, ensure_user, is_admin, has_perm, get_log_channels_db, get_user_currency,
)
from utils.flags import flag_for, clean_name
from utils.keyboards import style_btn
from utils.markup import format_dual_from_inr
from utils.helpers import get_bot_instance
from utils import manual_stock as ms

PAGE_SIZE = 8

# uid -> {"step": str, "data": {...}}
mtg_wizard = {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _safe_edit(event, text, buttons):
    try:
        return event.edit(text, buttons=buttons, parse_mode="html")
    except Exception:
        try:
            return event.respond(text, buttons=buttons, parse_mode="html")
        except Exception as exc:  # pragma: no cover
            logger.warning(f"mtg edit failed: {exc}")


def _currency(uid):
    try:
        return get_user_currency(uid)
    except Exception:
        return "INR"


def _price(value, uid):
    """Manual-stock price is already the final selling price -> show INR + USDT."""
    return format_dual_from_inr(float(value or 0))


def _balance(uid):
    row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


async def _notify_log(text):
    """Best-effort copy of a sale to the configured log channels."""
    try:
        bot_inst = get_bot_instance() or bot
        for ch in get_log_channels_db():
            try:
                await bot_inst.send_message(int(ch), text, parse_mode="html")
            except Exception:
                pass
    except Exception:
        pass


# --------------------------------------------------------------------------
# User panel
# --------------------------------------------------------------------------
async def show_home(event, page=1):
    uid = event.sender_id
    ensure_user(uid)
    countries = ms.manual_countries()
    total = len(countries)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    chunk = countries[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    stats = ms.manual_stats()
    if not chunk:
        msg = (
            "<blockquote expandable>📱 <b>Basic Telegram Accounts</b>\n\n"
            "🕓 <b>No accounts in stock right now.</b>\n"
            "Fresh accounts are added manually by the admin — please check back "
            "soon, or browse the other panels meanwhile.</blockquote>"
        )
        btns = [
            [style_btn("🧩 All Panels", b"pp_hub", "primary", icon=5409320020058584473)],
            [style_btn("🔙 Back to Buy Menu", b"buy_menu_main", "danger", icon=6129812419028982717)],
        ]
        return await _safe_edit(event, msg, btns)

    btns, row = [], []
    for country, count, min_price in chunk:
        label = f"{flag_for(country)} {clean_name(country)} · {_price(min_price, uid)}"
        row.append(style_btn(label[:60], f"mtg_c|{country}", "success"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    nav = []
    if page > 1:
        nav.append(style_btn("⬅️ Prev", f"mtg_pg|{page - 1}", "primary", icon=6129627894349045589))
    nav.append(style_btn(f"📄 {page}/{total_pages}", f"mtg_pg|{page}", "primary"))
    if page < total_pages:
        nav.append(style_btn("Next ➡️", f"mtg_pg|{page + 1}", "primary", icon=6129732880529628243))
    btns.append(nav)
    btns.append([
        style_btn("🔄 Refresh", b"mtg_home", "success", icon=5409320020058584473),
        style_btn("🔙 Back", b"buy_menu_main", "danger", icon=6129812419028982717),
    ])

    msg = (
        "<blockquote expandable>📱 <b>Basic Telegram Accounts</b>\n\n"
        "✅ Ready-to-use Telegram accounts, added manually by the admin.\n"
        "🌍 Pick a country to see live availability & prices.\n\n"
        f"📦 <b>In stock:</b> {stats['available']} accounts across {total} "
        f"{'country' if total == 1 else 'countries'}\n"
        f"<i>Page {page}/{total_pages}</i></blockquote>"
    )
    await _safe_edit(event, msg, btns)


async def show_country(event, country, page=1):
    uid = event.sender_id
    ensure_user(uid)
    accounts = ms.list_manual_accounts(available_only=True, country=country, limit=100)
    total = len(accounts)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    chunk = accounts[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    if not chunk:
        msg = (
            f"<blockquote expandable>{flag_for(country)} <b>{html.escape(clean_name(country))}</b>\n\n"
            "🕓 No accounts left for this country. Please pick another one.</blockquote>"
        )
        btns = [[style_btn("🔙 Back", b"mtg_home", "danger", icon=6129812419028982717)]]
        return await _safe_edit(event, msg, btns)

    btns = []
    for acct in chunk:
        label = f"📱 +{acct['phone']} · {_price(acct['price'], uid)}"
        btns.append([style_btn(label[:60], f"mtg_buy|{acct['id']}", "success")])
    nav = []
    if page > 1:
        nav.append(style_btn("⬅️ Prev", f"mtg_cp|{country}|{page - 1}", "primary", icon=6129627894349045589))
    nav.append(style_btn(f"📄 {page}/{total_pages}", f"mtg_cp|{country}|{page}", "primary"))
    if page < total_pages:
        nav.append(style_btn("Next ➡️", f"mtg_cp|{country}|{page + 1}", "primary", icon=6129732880529628243))
    btns.append(nav)
    btns.append([style_btn("🔙 Back to Countries", b"mtg_home", "danger", icon=6129812419028982717)])

    msg = (
        f"<blockquote expandable>{flag_for(country)} <b>{html.escape(clean_name(country))}</b>\n\n"
        f"📦 <b>{total}</b> {'account' if total == 1 else 'accounts'} available.\n"
        "Tap an account to see details and confirm your purchase.</blockquote>"
    )
    await _safe_edit(event, msg, btns)


async def show_confirm(event, account_id):
    uid = event.sender_id
    acct = ms.get_manual_account(account_id)
    if not acct or not acct.get("available"):
        return await event.answer("⚠️ This account was just sold. Please pick another.", alert=True)
    bal = _balance(uid)
    price = float(acct["price"] or 0)
    enough = bal >= price
    msg = (
        f"<blockquote expandable>{flag_for(acct['country'])} <b>Confirm Purchase</b>\n\n"
        f"🌍 <b>Country:</b> {html.escape(clean_name(acct['country']))}\n"
        f"📱 <b>Number:</b> <code>+{html.escape(acct['phone'])}</code>\n"
        f"💵 <b>Price:</b> {_price(price, uid)}\n"
        f"👛 <b>Your balance:</b> {_price(bal, uid)}\n\n"
        + ("✅ You have enough balance. Tap <b>Pay & Buy</b> to get the account instantly."
           if enough else "❌ Insufficient balance. Please top up first.")
        + "</blockquote>"
    )
    btns = []
    if enough:
        btns.append([style_btn("✅ Pay & Buy", f"mtg_pay|{account_id}", "success", icon=5409320020058584473)])
    else:
        btns.append([style_btn("💳 Add Funds", b"open_deposit_menu", "primary", icon=5409271925014801629)])
    btns.append([style_btn("🔙 Back", f"mtg_c|{acct['country']}", "danger", icon=6129812419028982717)])
    await _safe_edit(event, msg, btns)


async def deliver_account(event, account_id):
    uid = event.sender_id
    result = ms.purchase_manual_account(uid, account_id)
    if not result.get("ok"):
        err = result.get("error")
        if err == "insufficient":
            return await event.answer("❌ Insufficient balance. Please top up first.", alert=True)
        if err == "not_found":
            return await event.answer("⚠️ This account was just sold. Please pick another.", alert=True)
        return await event.answer("⚠️ Could not complete the purchase. Please try again.", alert=True)

    acct = result["account"]
    twofa = (acct.get("twofa") or "").strip()
    session = (acct.get("session") or "").strip()
    lines = [
        "<blockquote expandable>✅ <b>Purchase Successful — Basic Telegram Account</b>\n",
        f"{flag_for(acct['country'])} <b>Country:</b> {html.escape(clean_name(acct['country']))}",
        f"📱 <b>Phone:</b> <code>+{html.escape(acct['phone'])}</code>",
        f"🔐 <b>2FA Password:</b> <code>{html.escape(twofa) if twofa else 'Not set'}</code>",
        f"💵 <b>Paid:</b> {_price(acct['price'], uid)}",
        f"{PE_ID} <b>Account ID:</b> <code>{acct['id']}</code>\n",
        "<i>Open Telegram → Add Account → enter the phone number. If Telegram "
        "asks for a code, use the session below with a Telethon client, or "
        "contact support.</i></blockquote>",
    ]
    msg = "\n".join(lines)
    btns = [
        [style_btn("📱 Basic Accounts", b"mtg_home", "primary", icon=5409320020058584473)],
        [style_btn("🏠 Main Menu", b"dashboard_main", "danger", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)

    # Deliver the session string as a text file too (if present).
    if session:
        try:
            fname = f"telegram_{acct['phone']}.session.txt"
            with open(fname, "w", encoding="utf-8") as fh:
                fh.write(
                    f"Phone: +{acct['phone']}\n"
                    f"2FA: {twofa or 'Not set'}\n"
                    f"Session: {session}\n"
                )
            await event.respond(
                "📄 <b>Your session file is attached.</b> Keep it private.",
                file=fname,
                parse_mode="html",
            )
        except Exception as exc:
            logger.warning(f"manual session delivery failed: {exc}")

    await _notify_log(
        f"🛒 <b>Manual TG Account Sold</b>\n"
        f"👤 Buyer: <code>{uid}</code>\n"
        f"🆔 Account: <code>{acct['id']}</code>\n"
        f"📱 +{acct['phone']}\n"
        f"💵 {_price(acct['price'], uid)}"
    )


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
def _can_add(uid):
    return is_admin(uid) and has_perm(uid, "p_add_stock")


def _can_manage(uid):
    return is_admin(uid) and (has_perm(uid, "p_manage_stock") or has_perm(uid, "p_add_stock"))


async def admin_list(event):
    uid = event.sender_id
    if not _can_manage(uid):
        return
    rows = ms.list_manual_accounts(available_only=False, limit=40)
    stats = ms.manual_stats()
    if not rows:
        return await event.reply("📭 <b>Manual stock is empty.</b>\nAdd with <code>/addtg</code>.",
                                 parse_mode="html")
    out = ["<blockquote expandable>📱 <b>Manual Telegram Stock</b>\n"]
    out.append(f"✅ Available: {stats['available']} · 💰 Sold: {stats['sold']} · "
               f"💵 Revenue: {stats['revenue']:.0f}\n")
    for r in rows:
        status = "✅" if r["available"] else "❌"
        out.append(
            f"{status} <code>#{r['id']}</code> {flag_for(r['country'])} "
            f"{html.escape(clean_name(r['country']))} · +{html.escape(r['phone'])} · "
            f"{r['price']:.0f}"
        )
    out.append("</blockquote>")
    await event.reply("\n".join(out), parse_mode="html")


async def admin_stats(event):
    if not _can_manage(event.sender_id):
        return
    s = ms.manual_stats()
    await event.reply(
        f"<blockquote>📊 <b>Manual Stock Stats</b>\n\n"
        f"✅ Available: <b>{s['available']}</b>\n"
        f"💰 Sold: <b>{s['sold']}</b>\n"
        f"💵 Revenue: <b>{s['revenue']:.2f}</b></blockquote>",
        parse_mode="html",
    )


async def admin_delete(event, arg):
    if not _can_manage(event.sender_id):
        return
    try:
        account_id = int(arg.strip())
    except (TypeError, ValueError):
        return await event.reply("Usage: <code>/deltg 12</code>", parse_mode="html")
    removed = ms.delete_manual_account(account_id)
    if removed:
        await event.reply(f"🗑️ Deleted manual account <code>#{account_id}</code>.", parse_mode="html")
    else:
        await event.reply(f"⚠️ No manual account with id <code>{account_id}</code>.", parse_mode="html")


async def admin_clear(event):
    if not _can_manage(event.sender_id):
        return
    n = ms.clear_manual_accounts()
    await event.reply(f"🧹 Cleared <b>{n}</b> manual account(s).", parse_mode="html")


async def admin_clear_old_stock(event):
    """Remove the OLD auto-imported Telethon stock + cached panel prices."""
    uid = event.sender_id
    if not _can_manage(uid):
        return
    try:
        before = cur.execute("SELECT COUNT(*) FROM stock").fetchone()[0]
        cur.execute("DELETE FROM stock")
        db.commit()
        # Drop cached live country/price lists so stale data can't reappear.
        try:
            from plugins import product_panels
            product_panels._cache.clear()
        except Exception:
            pass
        await event.reply(
            f"🧹 <b>Old stock cleared.</b>\n\n"
            f"Removed <b>{before}</b> old account(s) from the legacy stock table.\n"
            f"Manual <i>Basic Telegram Accounts</i> were left untouched.",
            parse_mode="html",
        )
    except Exception as exc:
        logger.error(f"clearoldstock failed: {exc}")
        await event.reply(f"❌ Failed to clear old stock: {exc}", parse_mode="html")


# ---- interactive add wizard ----------------------------------------------
async def wizard_start(event):
    uid = event.sender_id
    if not _can_add(uid):
        return
    mtg_wizard[uid] = {"step": "country", "data": {}}
    await event.reply(
        "<blockquote>📱 <b>Add Basic Telegram Account</b>\n\n"
        "Step <b>1/5</b> — send the <b>country</b> name (e.g. <code>India</code>).\n\n"
        "<i>Send /cancel at any time to stop.</i></blockquote>",
        parse_mode="html",
    )


async def wizard_handle(event):
    uid = event.sender_id
    state = mtg_wizard.get(uid)
    if not state:
        return False
    text = (event.raw_text or "").strip()
    if text.lower() in ("/cancel", "cancel"):
        mtg_wizard.pop(uid, None)
        await event.reply("❌ Cancelled.")
        return True
    if text.startswith("/"):
        return False

    step = state["step"]
    data = state["data"]

    if step == "country":
        data["country"] = text
        state["step"] = "phone"
        await event.reply(
            "<blockquote>Step <b>2/5</b> — send the <b>phone number</b> "
            "(with country code, e.g. <code>+919876543210</code>).</blockquote>",
            parse_mode="html",
        )
        return True

    if step == "phone":
        data["phone"] = text.lstrip("+").replace(" ", "")
        state["step"] = "price"
        await event.reply(
            "<blockquote>Step <b>3/5</b> — send the <b>selling price</b> "
            "(a number, e.g. <code>150</code>).</blockquote>",
            parse_mode="html",
        )
        return True

    if step == "price":
        try:
            data["price"] = float(text.replace("₹", "").replace(",", "").strip())
        except ValueError:
            await event.reply("⚠️ Please send a valid number, e.g. <code>150</code>.", parse_mode="html")
            return True
        state["step"] = "twofa"
        await event.reply(
            "<blockquote>Step <b>4/5</b> — send the <b>2FA password</b>, "
            "or send <code>skip</code> if there is none.</blockquote>",
            parse_mode="html",
        )
        return True

    if step == "twofa":
        data["twofa"] = "" if text.lower() in ("skip", "none", "-") else text
        state["step"] = "session"
        await event.reply(
            "<blockquote>Step <b>5/5</b> — paste the <b>session string</b>, "
            "or send <code>skip</code> if you only want to store the number.</blockquote>",
            parse_mode="html",
        )
        return True

    if step == "session":
        data["session"] = "" if text.lower() in ("skip", "none", "-") else text
        try:
            account_id = ms.add_manual_account(
                country=data["country"], phone=data["phone"],
                session=data["session"], twofa=data["twofa"],
                price=data["price"], added_by=uid,
            )
        except Exception as exc:
            mtg_wizard.pop(uid, None)
            await event.reply(f"❌ Failed to add account: {exc}", parse_mode="html")
            return True
        mtg_wizard.pop(uid, None)
        await event.reply(
            f"<blockquote>✅ <b>Account added!</b>\n\n"
            f"🆔 ID: <code>#{account_id}</code>\n"
            f"{flag_for(data['country'])} {html.escape(clean_name(data['country']))} · "
            f"+{html.escape(data['phone'])} · {data['price']:.0f}</blockquote>",
            parse_mode="html",
        )
        return True

    return False


async def admin_add_oneline(event, body):
    uid = event.sender_id
    if not _can_add(uid):
        return
    parts = [p.strip() for p in body.split("|")]
    if len(parts) < 3:
        return await event.reply(
            "Usage:\n<code>/addtg Country | phone | price | 2fa | session</code>\n"
            "or send <code>/addtg</code> for the step-by-step wizard.",
            parse_mode="html",
        )
    country, phone, price = parts[0], parts[1], parts[2]
    twofa = parts[3] if len(parts) > 3 else ""
    session = parts[4] if len(parts) > 4 else ""
    try:
        price_val = float(price.replace("₹", "").replace(",", "").strip())
        account_id = ms.add_manual_account(country, phone, session, twofa, price_val, added_by=uid)
    except Exception as exc:
        return await event.reply(f"❌ Failed: {exc}", parse_mode="html")
    await event.reply(
        f"✅ Added <code>#{account_id}</code> — {flag_for(country)} "
        f"{html.escape(clean_name(country))} · +{html.escape(phone.lstrip('+'))} · {price_val:.0f}",
        parse_mode="html",
    )


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
def register_manual_accounts(bot):
    ms.ensure_manual_table()

    @bot.on(events.CallbackQuery(pattern=r"^mtg_"))
    async def cb_manual(e):
        data = (e.data or b"").decode()
        uid = e.sender_id
        ensure_user(uid)
        if data == "mtg_home":
            return await show_home(e, 1)
        if data.startswith("mtg_pg|"):
            try:
                return await show_home(e, int(data.split("|", 1)[1]))
            except ValueError:
                return await show_home(e, 1)
        if data.startswith("mtg_c|"):
            return await show_country(e, data.split("|", 1)[1])
        if data.startswith("mtg_cp|"):
            _, country, page = data.split("|", 2)
            try:
                page = int(page)
            except ValueError:
                page = 1
            return await show_country(e, country, page)
        if data.startswith("mtg_buy|"):
            try:
                return await show_confirm(e, int(data.split("|", 1)[1]))
            except ValueError:
                return await e.answer("Invalid account.", alert=True)
        if data.startswith("mtg_pay|"):
            try:
                return await deliver_account(e, int(data.split("|", 1)[1]))
            except ValueError:
                return await e.answer("Invalid account.", alert=True)

    @bot.on(events.NewMessage(pattern=r"(?i)^/basictg(?:@\w+)?$"))
    async def cmd_basictg(e):
        await show_home(e, 1)

    @bot.on(events.NewMessage(pattern=r"(?i)^/addtg(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_addtg(e):
        if not _can_add(e.sender_id):
            return
        body = e.pattern_match.group(1)
        if body:
            return await admin_add_oneline(e, body)
        return await wizard_start(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/listtg(?:@\w+)?$"))
    async def cmd_listtg(e):
        await admin_list(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/tgstats(?:@\w+)?$"))
    async def cmd_tgstats(e):
        await admin_stats(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/deltg(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_deltg(e):
        await admin_delete(e, e.pattern_match.group(1) or "")

    @bot.on(events.NewMessage(pattern=r"(?i)^/cleartg(?:@\w+)?$"))
    async def cmd_cleartg(e):
        await admin_clear(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/clearoldstock(?:@\w+)?$"))
    async def cmd_clearold(e):
        await admin_clear_old_stock(e)

    # Wizard text capture (registered last so commands above win).
    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out and bool(e.text)
                              and e.sender_id in mtg_wizard))
    async def mtg_wizard_router(e):
        handled = await wizard_handle(e)
        if handled:
            raise events.StopPropagation
