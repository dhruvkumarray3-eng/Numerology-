import os
from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db, get_support_url, to_usd, get_flag_by_country_name, is_admin, get_bot_mode
from config import P_NO, P_MONEY, P_INR, P_GIFT, P_USERS, PE_LOCATION, PE_GIFT, PE_CROWN
from utils.states import session_buy_state, deposit_input, active_orders, waiting_proof
from plugins.start import send_main_menu
from utils.terms import get_terms_message
from utils.helpers import check_channel_joined
from utils.keyboards import (
    style_btn, style_url, SEARCH_EMOJI_ID,
    menu_label_key, is_menu_label,
)
from utils.lzt import COUNTRY_TO_LZT


def _clear_buy_state(uid):
    """Drop a half-finished country search before showing a menu screen.

    Without this, tapping a reply-keyboard button while the Buy flow is
    waiting for a country made the catch-all text handler in ``plugins/buy.py``
    treat the button label as a country query and answer "No country found".
    """
    try:
        from plugins.buy import search_state, user_states
        search_state.pop(uid, None)
        if user_states.get(uid) in (None, "AWAITING_COUNTRY"):
            user_states.pop(uid, None)
    except Exception:
        pass


async def send_stock_page(event, page=1):
    """Live stock list with REAL counts (never a fake "40+").

    Uses the same honest country list as the buy flow, so a country with no
    accounts shows "no stock" instead of a made-up number.
    """
    from plugins.buy import get_countries_list

    limit = 10
    offset = (page - 1) * limit

    try:
        rows = await get_countries_list()
    except Exception:
        rows = []

    if not rows:
        msg = (f"<blockquote>{PE_LOCATION} <b>\U0001F4E6 \u029f\u026a\u1d20\u1d07 "
               f"\ua731\u1d1b\u1d0f\u1d04\u1d0b</b>\n\n\u26a0\ufe0f No stock available "
               f"right now. Please check back shortly.</blockquote>")
        if isinstance(event, events.CallbackQuery.Event):
            try:
                return await event.edit(msg)
            except MessageNotModifiedError:
                return
        return await event.respond(msg)

    total_countries = len(rows)
    total_stock = sum(c for _, c in rows)
    total_pages = max(1, (total_countries + limit - 1) // limit)
    page = max(1, min(page, total_pages))
    page_items = rows[offset:offset + limit]

    msg = (f"<blockquote>{PE_LOCATION} <b>\U0001F4E6 \u1d00\u1d20\u1d00\u026a\u029f\u1d00\u0299\u029f\u1d07 \ua731\u1d1b\u1d0f\u1d04\u1d0b</b> \u2014 {total_stock} \u1d1b\u1d0f\u1d1b\u1d00\u029f "
           f"\ua731\u1d1b\u1d0f\u1d04\u1d0b \u00b7 \u1d18\u1d00\u0262\u1d07 {page}/{total_pages}</blockquote>\n\n")
    for cn, cnt in page_items:
        flag = get_flag_by_country_name(cn)
        if cnt and int(cnt) > 0:
            msg += f"<blockquote>{flag} <b>{cn}</b> \u2014 {cnt} \u1d00\u1d04\u1d04\u1d0f\u1d1c\u0274\u1d1bs</blockquote>\n"
        else:
            msg += f"<blockquote>{flag} <b>{cn}</b> \u2014 \u26aa no stock</blockquote>\n"

    nav = []
    if page > 1:
        nav.append(style_btn("\u2b05\ufe0f \u1d18\u0280\u1d07\u1d20", f"stk_pg|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total_countries:
        nav.append(style_btn("\u1d0d\u1d07x\u1d1b \u27a1\ufe0f", f"stk_pg|{page+1}", "primary", icon=6129732880529628243))

    btns = []
    if nav:
        btns.append(nav)
    btns.append([style_btn("\U0001F50D Search Country", "search_country_btn", "primary", icon=SEARCH_EMOJI_ID)])
    btns.append([style_btn("\U0001F519 Back", "dashboard_main", "danger", icon=6129812419028982717)])

    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)


async def show_more_menu(event):
    pct_row = cur.execute("SELECT value FROM settings WHERE key='ref_percent'").fetchone()
    pct = pct_row[0] if pct_row else "3"
    
    from config import TERMS_URL, OWNER_URL
    from database import get_support_url
    
    msg = (f"<blockquote>💬 <b>𝐌ᴏʀᴇ 𝐎ᴘᴛɪᴏɴs & 𝐓ᴏᴏʟs</b>\n\n"
           f"🎁 <b>𝐑ᴇғᴇʀ & 𝐄ᴀʀɴ:</b> 𝐄ᴀʀɴ {pct}% ᴏғ ᴀʟʟ ғʀɪᴇɴᴅ ᴅᴇᴘᴏsɪᴛs!\n"
           f"📊 <b>𝐋ɪᴠᴇ 𝐒ᴛᴏᴄᴋ:</b> 𝐕ɪᴇᴡ ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴄᴄᴏᴜɴᴛs ᴀᴄʀᴏss ᴀʟʟ ᴄᴏᴜɴᴛʀɪᴇs.\n"
           f"📜 <b>𝐓ᴇʀᴍs & 𝐑ᴜʟᴇs:</b> 𝐑ᴇᴀᴅ ᴏᴜʀ sᴇʀᴠɪᴄᴇ ᴛᴇʀᴍs.</blockquote>")
           
    btns = [
        [style_btn("🎁 Refer & Earn", b"view_referrals", "success", icon=5354889508674360491)],
        [style_btn("📊 Live Stock", b"stk_pg|1", "primary", icon=6129627894349045589)],
        [style_url("📜 Terms & Conditions", TERMS_URL if (TERMS_URL and str(TERMS_URL).strip().startswith("http")) else get_support_url(), "primary", icon=6129732880529628243)],
        [style_url("\U0001F465 Support Group", get_support_url(), "success", icon=6129732880529628243)],
        [style_url("\U0001F451 Owner", OWNER_URL, "danger", icon=5409166771330494453)],
        [style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐃ᴀsʜʙᴏᴀʀᴅ", b"dashboard_main", "danger", icon=6129812419028982717)]
    ]
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

async def show_refer_menu(bot, event):
    import urllib.parse
    uid = event.sender_id
    me = await bot.get_me()
    bot_username = me.username or ""
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
    ref_count = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
    pct_row = cur.execute("SELECT value FROM settings WHERE key='ref_percent'").fetchone()
    pct = pct_row[0] if pct_row else 3
    
    msg = (f"<blockquote>{P_GIFT} <b>🎁 𝐑ᴇғᴇʀ & 𝐄ᴀʀɴ</b>\n\n"
           f"{P_USERS} <b>👥 𝐘ᴏᴜʀ 𝐑ᴇғᴇʀʀᴀʟs:</b> <code>{ref_count}</code>\n"
           f"💲 <b>𝐁ᴏɴᴜs:</b> <code>{pct}%</code> ᴏғ ᴇᴠᴇʀʏ ᴅᴇᴘᴏsɪᴛ\n\n"
           f"🔗 <b>𝐘ᴏᴜʀ 𝐋ɪɴᴋ:</b>\n<code>{ref_link}</code>\n\n"
           f"<i>𝐒ʜᴀʀᴇ ᴛʜɪs ʟɪɴᴋ ᴡɪᴛʜ ғʀɪᴇɴᴅs. 𝐖ʜᴇɴ ᴛʜᴇʏ ᴅᴇᴘᴏsɪᴛ, ʏᴏᴜ ᴇᴀʀɴ {pct}%!</i></blockquote>")
           
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote('🔥 Join TG Account Robot for cheap Telegram & WhatsApp Accounts, SMM Services & Source Codes!')}"
    btns = [
        [style_url("🔗 𝐒ʜᴀʀᴇ 𝐋ɪɴᴋ ↗️", share_url, "success", icon=5354889508674360491)],
        [style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐃ᴀsʜʙᴏᴀʀᴅ", b"dashboard_main", "danger", icon=6129812419028982717)]
    ]
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

def register_callbacks(bot):
    @bot.on(events.CallbackQuery(pattern=b"^more_menu$"))
    async def cb_more_menu(e):
        await show_more_menu(e)

    @bot.on(events.CallbackQuery(pattern=r"^view_referrals$"))
    async def cb_view_referrals(e):
        await show_refer_menu(bot, e)

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and menu_label_key(e.raw_text) == "refer"))
    async def msg_refer(e):
        _clear_buy_state(e.sender_id)
        await show_refer_menu(bot, e)
        raise events.StopPropagation

    @bot.on(events.CallbackQuery(pattern=r"^stk_pg\|(\d+)$"))
    async def cb_stk_pg(e):
        page = int(e.pattern_match.group(1).decode())
        await send_stock_page(e, page)

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and menu_label_key(e.raw_text) == "stock"))
    async def msg_stock(e):
        _clear_buy_state(e.sender_id)
        await send_stock_page(e, 1)
        raise events.StopPropagation

    @bot.on(events.CallbackQuery(pattern=b"^tc_accept$"))
    async def cb_tc_accept(e):
        uid = e.sender_id
        cur.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (uid,))
        db.commit()
        await e.answer("✅ Terms Accepted!", alert=True)
        try: await e.delete()
        except: pass
        await send_main_menu(bot, None, uid)

    @bot.on(events.CallbackQuery(pattern=b"^tc_reject$"))
    async def cb_tc_reject(e):
        try: await e.edit(f"{P_NO} You cannot use the bot without accepting the terms.")
        except MessageNotModifiedError: pass

    @bot.on(events.CallbackQuery(pattern=b"^cancel_action$"))
    async def cb_cancel_action(e):
        uid = e.sender_id
        deposit_input.pop(uid, None)
        session_buy_state.pop(uid, None)
        waiting_proof.pop(uid, None)
        try: await e.delete()
        except Exception: pass
        await e.answer("Cancelled", alert=False)

    @bot.on(events.CallbackQuery(pattern=b"^verify_join$"))
    async def cb_verify_join(e):
        uid = e.sender_id
        from utils.helpers import get_unjoined_channels
        from utils.keyboards import style_btn
        from config import PE_FLOWER, PE_LOCATION

        unjoined = await get_unjoined_channels(bot, uid)
        
        if not unjoined:
            # All channels joined!
            await e.answer("✅ Verification successful!", alert=True)
            row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (uid,)).fetchone()
            terms_acc = row[0] if row else 0
            if not terms_acc:
                from utils.keyboards import get_terms_buttons
                from utils.helpers import safe_edit_or_resend
                terms_message = get_terms_message()
                if terms_message is None:
                    await safe_edit_or_resend(
                        e,
                        "⚠️ Terms & Conditions are temporarily unavailable. "
                        "Please try /start again later.",
                    )
                else:
                    # The join screen is a PHOTO, and Telegram caps media
                    # captions at 1024 chars while the Terms text is longer.
                    # Editing it raised MediaCaptionTooLongError and the user
                    # never reached the Terms buttons.  safe_edit_or_resend
                    # falls back to delete + resend as a plain text message
                    # (4096 chars) so this can never get stuck again.
                    await safe_edit_or_resend(
                        e, terms_message, buttons=get_terms_buttons()
                    )
            else:
                try: await e.delete()
                except: pass
                await send_main_menu(bot, None, uid)
        else:
            # Show only unjoined channels
            remaining = len(unjoined)
            await e.answer(f"❌ {remaining} channel(s)/group(s) not joined yet!", alert=True)
            buttons = []
            for url, idx in unjoined:
                btn_label = "💬 𝐉ᴏɪɴ 𝐆ʀᴏᴜᴘ" if ("+" in url or "joinchat" in url or idx == 2) else "📢 𝐉ᴏɪɴ 𝐂ʜᴀɴɴᴇʟ"
                buttons.append([style_url(btn_label, url, "primary", icon=5409119256107297715)])
            buttons.append([style_btn("𝐕ᴇʀɪғʏ 𝐉ᴏɪɴᴇᴅ", b"verify_join", "success", icon=6129627894349045589)])
            msg = f"<blockquote>{PE_FLOWER} <b>𝐘ᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟs & ɢʀᴏᴜᴘ ғɪʀsᴛ!</b></blockquote>\n<blockquote>{PE_LOCATION} {remaining} ᴄʜᴀɴɴᴇʟ(s)/ɢʀᴏᴜᴘ(s) ʀᴇᴍᴀɪɴɪɴɢ. 𝐉ᴏɪɴ ᴀɴᴅ ᴛᴀᴘ <b>𝐕ᴇʀɪғʏ 𝐉ᴏɪɴᴇᴅ</b>.</blockquote>"
            from utils.helpers import safe_edit_or_resend
            await safe_edit_or_resend(e, msg, buttons=buttons)

    # ── Keyboard Button Handlers ──

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and menu_label_key(e.raw_text) == "my_orders"))
    async def msg_my_orders(e):
        _clear_buy_state(e.sender_id)
        uid = e.sender_id
        rows = cur.execute("SELECT phone, country, price, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
        if not rows:
            return await e.respond(f"<blockquote>{PE_GIFT} <b>𝐌ʏ 𝐎ʀᴅᴇʀs</b></blockquote>\n\n<blockquote>𝐍ᴏ ᴏʀᴅᴇʀs ʏᴇᴛ. 𝐁ᴜʏ ʏᴏᴜʀ ғɪʀsᴛ ᴀᴄᴄᴏᴜɴᴛ!</blockquote>")
        msg = f"<blockquote>{PE_GIFT} <b>𝐌ʏ 𝐎ʀᴅᴇʀs</b> (𝐋ᴀsᴛ 10)</blockquote>\n\n"
        for ph, cn, pr, dt in rows:
            flag = get_flag_by_country_name(cn)
            msg += f"<blockquote>{flag} {cn} | <code>{ph}</code>\n{P_MONEY} {P_INR}{pr} | 📅 {dt[:10]}</blockquote>\n"
        await e.respond(msg)

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and menu_label_key(e.raw_text) == "balance"))
    async def msg_balance(e):
        _clear_buy_state(e.sender_id)
        uid = e.sender_id
        row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        bal = row[0] if row else 0
        msg = (f"<blockquote>{PE_CROWN} <b>𝐘ᴏᴜʀ 𝐁ᴀʟᴀɴᴄᴇ</b></blockquote>\n\n"
               f"<blockquote>{P_MONEY} <b>𝐁ᴀʟᴀɴᴄᴇ:</b> <code>{P_INR}{bal}</code>\n"
               f"💲 <b>𝐔𝐒𝐃:</b> <code>${to_usd(bal):.2f}</code></blockquote>")
        await e.respond(msg)

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and menu_label_key(e.raw_text) == "support"))
    async def msg_support(e):
        _clear_buy_state(e.sender_id)
        url = get_support_url()
        from config import OWNER_URL, OWNER_USERNAME, SUPPORT_USERNAME
        msg = (f"<blockquote>\U0001F4E9 <b>𝐒\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b</b></blockquote>\n\n"
               f"<blockquote>𝐅\u1d0f\u0280 \u1d00\u0274\u028f \u026ass\u1d1c\u1d07s \u1d0f\u0280 \u01eb\u1d1c\u1d07s\u1d1b\u026a\u1d0f\u0274s, \u1d04\u1d0f\u0274\u1d1b\u1d00\u1d04\u1d1b \u1d0f\u1d1c\u0280 s\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b:\n\n"
               f"\U0001F465 <b>Support Group:</b> {SUPPORT_USERNAME}\n"
               f"\U0001F451 <b>Owner:</b> {OWNER_USERNAME}</blockquote>")
        btns = [
            [style_url("\U0001F465 Support Group", url, "success", icon=6129732880529628243)],
            [style_url("\U0001F451 Owner", OWNER_URL, "danger", icon=5409166771330494453)],
        ]
        await e.respond(msg, buttons=btns)
