from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import cur, to_usd
from config import (PE_KISS, PE_CROWN, PE_FLOWER, P_ID, P_MONEY, P_CARD, P_USERS, P_CAL,
                     P_GIFT, P_CART, P_USDT, P_PHONE, PE_ID, PE_CARD, PE_TROPHY, PE_STAR)
from datetime import datetime
from utils.markup import format_user_amount
from utils.levels import compute_level, tier_label
from utils.i18n import t
from utils.helpers import get_bot_username
from utils.keyboards import style_btn, menu_label_key


async def profile_handler(bot, event):
    uid = event.sender_id
    row = cur.execute("SELECT balance, total_deposited, joined_date, discount FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row: return await bot.send_message(event.chat_id, "⚠️ Error: Please type /start to initialize your account.")
    
    bal, dep, date, discount = row
    ref_count_row = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()
    ref_count = ref_count_row[0] if ref_count_row else 0
    bot_username = await get_bot_username(bot)
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else None
    disc_msg = f"\n{P_GIFT} Active Discount: <b>{discount}% OFF</b>" if discount > 0 else ""
    ref_block = (f"{P_USERS} <b>{t(uid, 'referral_link')}:</b>\n<code>{ref_link}</code>\n\n"
                 if ref_link else
                 f"{P_USERS} <b>Referral Link:</b>\n<i>Set a public bot username to enable referrals.</i>\n\n")

    bal_txt = format_user_amount(bal, uid=uid)
    dep_txt = format_user_amount(dep, uid=uid)

    msg = (f"<blockquote expandable>{PE_KISS} <b>𝕌𝕤𝕖𝕣 ℙ𝕣𝕠𝕗𝕚𝕝𝕖</b></blockquote>\n\n"
           f"<blockquote>{PE_ID} {t(uid, 'user_id')}: <tg-spoiler><code>{uid}</code></tg-spoiler>\n"
           f"{PE_CARD} {t(uid, 'balance')}: <tg-spoiler><code>{bal_txt}</code></tg-spoiler>\n"
           f"{P_CARD} {t(uid, 'deposited')}: <code>{dep_txt}</code>{disc_msg}\n"
           f"{P_USERS} {t(uid, 'referred_users')}: <b>{ref_count}</b>\n"
           f"{P_CAL} {t(uid, 'joined')}: {date[:10]}</blockquote>\n\n"
           f"<blockquote>{ref_block}</blockquote>\n"
           f"<blockquote><i>{t(uid, 'share_note')}</i></blockquote>")
    await bot.send_message(event.chat_id, msg)


async def stats_handler(bot, event, is_callback=False):
    uid = event.sender_id
    row = cur.execute("SELECT total_deposited FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row: return
    dep = row[0]
    o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (uid,)).fetchone()
    total_orders = o_row[0] if o_row else 0
    spent = o_row[1] if o_row and o_row[1] else 0
    ref_row = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()
    ref_count = ref_row[0] if ref_row else 0

    # Live level snapshot — deposits AND spend both count (utils.levels).
    lvl = compute_level(uid)
    spent_txt = format_user_amount(spent, uid=uid)
    dep_txt = format_user_amount(dep, uid=uid)

    if lvl["next_tier"] is not None:
        need_txt = format_user_amount(lvl["need"], uid=uid)
        tier_line = (f"{PE_TROPHY} <b>{t(uid, 'level')}:</b> {tier_label(lvl['tier'])}\n"
                     f"{PE_STAR} <b>{t(uid, 'next_tier')}:</b> {tier_label(lvl['next_tier'])} "
                     f"<i>({t(uid, 'more_needed', amount=need_txt)})</i>")
    else:
        tier_line = (f"{PE_TROPHY} <b>{t(uid, 'level')}:</b> {tier_label(lvl['tier'])}\n"
                     f"{PE_STAR} <i>{t(uid, 'max_level')}</i>")

    msg = (f"<blockquote>{PE_CROWN} <b>𝕄𝕪 𝕊𝕥𝕒𝕥𝕚𝕤𝕥𝕚𝕔𝕤</b></blockquote>\n\n"
           f"<blockquote>{P_CART} <b>{t(uid, 'accounts_bought')}:</b> {total_orders}\n"
           f"{P_USERS} <b>{t(uid, 'referrals')}:</b> {ref_count}\n"
           f"{P_MONEY} <b>{t(uid, 'total_spent')}:</b> <code>{spent_txt}</code>\n"
           f"{P_CARD} <b>{t(uid, 'total_deposited')}:</b> <tg-spoiler><code>{dep_txt}</code></tg-spoiler>\n"
           f"{tier_line}</blockquote>\n"
           f"<blockquote>{PE_CARD} <b>{t(uid, 'deposit_vs_spend')}:</b> "
           f"<code>{dep_txt}</code> ▸ <code>{spent_txt}</code></blockquote>")

    btns = [
        [style_btn(f"🧾 {t(uid, 'view_purchases')}", b"page_purchases_1", "primary", icon=5409098988156629257)],
        [style_btn(f"🎁 {t(uid, 'referral_logs')}", b"view_referrals", "success", icon=5354889508674360491)],
    ]
    if is_callback:
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else: await bot.send_message(event.chat_id, msg, buttons=btns)


async def send_purchase_page(event, uid, page):
    limit = 5
    offset = (page - 1) * limit
    t_row = cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)).fetchone()
    total = t_row[0] if t_row else 0
    rows = cur.execute("SELECT phone, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?", (uid, limit, offset)).fetchall()
    
    msg = f"<blockquote>{PE_FLOWER} <b>ℙ𝕦𝕣𝕔𝕙𝕒𝕤𝕖 ℍ𝕚𝕤𝕥𝕠𝕣𝕪</b>\nℙ𝕒𝕘𝕖 {page}\n\n"
    if not rows: msg += "ℕ𝕠 𝕡𝕦𝕣𝕔𝕙𝕒𝕤𝕖𝕤 𝕗𝕠𝕦𝕟𝕕."
    else:
        for ph, d in rows:
            try:
                dt = datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
                d_str = dt.strftime("%a %b %d %H:%M:%S %Y")
            except:
                d_str = d
            msg += f"<blockquote>{P_PHONE} {ph}\n{P_CAL} {d_str}\n────────────────</blockquote>\n"
            
    nav = []
    if page > 1: nav.append(style_btn("⬅️ ℙ𝕣𝕖𝕧", f"page_purchases_{page-1}".encode(), "primary", icon=6129812419028982717))
    nav.append(style_btn(f"🔙 {t(uid, 'back')}", b"back_to_stats", "danger", icon=6129812419028982717))
    if offset + limit < total: nav.append(style_btn("ℕ𝕖𝕩𝕥 ➡️", f"page_purchases_{page+1}".encode(), "primary", icon=5409320020058584473))
    await event.edit(msg, buttons=[nav] if nav else None)


def register_profile(bot):
    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and menu_label_key(e.raw_text) == "profile"))
    async def msg_profile(e):
        await profile_handler(bot, e)
        raise events.StopPropagation

    @bot.on(events.CallbackQuery(pattern=b"^profile_stats$"))
    async def cb_profile_stats(e):
        await stats_handler(bot, e, is_callback=True)

    @bot.on(events.NewMessage(pattern=r"(?i)^(My Stats)$"))
    async def msg_stats(e):
        await stats_handler(bot, e)

    @bot.on(events.CallbackQuery(pattern=r"^page_purchases_(\d+)$"))
    async def cb_purchase_page(e):
        page = int(e.pattern_match.group(1).decode())
        await send_purchase_page(e, e.sender_id, page)

    @bot.on(events.CallbackQuery(pattern=r"^back_to_stats$"))
    async def cb_back_to_stats(e):
        await stats_handler(bot, e, is_callback=True)
