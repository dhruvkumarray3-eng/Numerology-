import html
from telethon import events, types, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db, ensure_user, is_user_banned, is_bot_online, is_admin, get_support_url, get_start_image_url
from utils.keyboards import get_persistent_menu, get_terms_buttons, get_join_buttons, style_btn, style_url
from utils.terms import get_terms_message
from utils.helpers import check_channel_joined, to_small_caps, send_preview_on_top
from config import (PE_FLOWER, PE_LOCATION, P_OFF, P_INR, TERMS_URL, UPDATES_URL,
                    QC_ID_PREFIX, logger, PE_LIGHTNING, PE_CROWN, PE_CHECK, PE_GIFT,
                    PE_ID, PE_USER, PE_TARGET, PE_TAG, PE_TROPHY, PE_CARD, PE_STAR,
                    ADMIN_ID, is_super_admin)
from utils.states import session_buy_state, deposit_input

async def send_main_menu(bot, event, uid):
    me = await bot.get_me()
    bot_name = me.first_name or "Store Bot"
    
    bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = float(bal_row[0]) if bal_row and bal_row[0] is not None else 0.0
    
    try:
        user_entity = await bot.get_entity(uid)
        first_name = user_entity.first_name or "User"
        username = f"@{user_entity.username}" if user_entity.username else "None"
    except Exception:
        first_name = "User"
        username = "None"
        
    start_img = get_start_image_url()
    support_url = get_support_url()
    support_handle = f"@{support_url.split('/')[-1]}" if support_url.startswith("https://t.me/") else support_url
    from config import OWNER_URL, OWNER_USERNAME
    owner_handle = OWNER_USERNAME
    
    update_link = UPDATES_URL
    feedback_link = support_url
    
    styled_name = to_small_caps(bot_name)
    
    # RDX ID is derived from this bot's own id, so it always matches the bot.
    rdx_id = f"{QC_ID_PREFIX}-{str(me.id)[-8:]}"

    dep_row = cur.execute("SELECT total_deposited FROM users WHERE user_id=?", (uid,)).fetchone()
    total_dep = float(dep_row[0]) if dep_row and dep_row[0] is not None else 0.0
    if total_dep >= 5000:
        vip = "💎 Diamond"
    elif total_dep >= 2000:
        vip = "🥇 Gold"
    elif total_dep >= 500:
        vip = "🥈 Silver"
    else:
        vip = "🏆 Bronze"

    msg = (f"<a href='{start_img}'>&#8203;</a>💬 <b>{html.escape(styled_name)}</b>\n\n"
           f"<blockquote expandable>"
           f"{PE_USER} <b>\U0001D40D\U0001D41A\U0001D426\U0001D41E:</b> {html.escape(first_name)}\n"
           f"{PE_ID} <b>\U0001D414s\U0001D407\U0001D404\U0001D411 \U0001D408\U0001D403:</b> <code>{uid}</code>\n"
           f"{PE_TARGET} <b>\U0001D414s\U0001D404\U0001D411\U0001D40D\U0001D400\U0001D426\U0001D404:</b> {username}\n"
           f"{PE_TAG} <b>\U0001D411\U0001D403\U0001D417 \U0001D408\U0001D403:</b> <code>{rdx_id}</code>\n"
           f"{PE_CARD} <b>\U0001D401\U0001D41A\U0001D425\U0001D41A\U0001D427\U0001D41C\U0001D41E:</b> <code>\u20b9{bal:.2f}</code>\n"
           f"{PE_TROPHY} <b>\U0001D415\U0001D408\U0001D40F:</b> {vip}"
           f"</blockquote>\n"
           f"<blockquote>{PE_LIGHTNING} <b>\U0001D412\U0001D42E\U0001D429\U0001D429\U0001D428\U0001D42B\U0001D42D :</b> <a href='{support_url}'>{support_handle}</a></blockquote>\n"
           f"<blockquote>{PE_CROWN} <b>\U0001D40E\u1d21\u0274\u1d07\u0280 :</b> <a href='{OWNER_URL}'>{owner_handle}</a></blockquote>")
    # Premium identity blocks — only shown to staff, using premium emojis.
    if is_admin(uid):
        staff = (f"<blockquote>{PE_CHECK} <b>𝓐𝓭𝓶𝓲𝓷 𝓘𝓓 :</b> <code>{uid}</code>\n"
                 f"{PE_GIFT} <b>𝓞𝔀𝓷𝓮𝓻 𝓘𝓓 :</b> <code>{ADMIN_ID}</code>")
        if is_super_admin(uid):
            staff += f"\n{PE_CROWN} <b>𝓢𝓾𝓹𝓮𝓻 𝓐𝓭𝓶𝓲𝓷 𝓘𝓓 :</b> <code>{uid}</code>"
        msg += staff + "</blockquote>"
           
    buttons = [
        [style_btn("📲 𝓑𝓾𝔂 𝓐𝓬𝓬𝓸𝓾𝓷𝓽", b"open_buy_categories", "success", icon=5440627033111557670)],
        [style_btn("📱 𝓐𝓵𝓵 𝓪𝓹𝓹𝓼 𝓪𝓬𝓬", b"all_apps_menu", "success", icon=5409320020058584473)],
        [style_btn("📱 𝓑𝓪𝓼𝓲𝓬 𝓣𝓮𝓵𝓮𝓰𝓻𝓪𝓶 𝓐𝓬𝓬𝓸𝓾𝓷𝓽𝓼", b"mtg_home", "success", icon=5409320020058584473)],
        [style_btn("💬 𝐖𝐡𝐚𝐭𝐬𝐀𝐩𝐩 𝐏𝐚𝐧𝐞𝐥", b"pp_open|whatsapp", "success", icon=5408995930416362034)],
        [style_btn("🧩 𝐀𝐥𝐥 𝐀𝐩𝐩𝐬 𝐎𝐓𝐏", b"pp_open|allotp", "success", icon=5409320020058584473)],
        [style_btn("🚀 𝓢𝓸𝓬𝓲𝓪𝓵 𝓶𝓮𝓭𝓲𝓪 𝓼𝓮𝓻𝓿𝓲𝓬𝓮𝓼", b"smm_menu_main", "success", icon=5408995930416362034)],
        [style_btn("🛒 𝓑𝓾𝔂 𝓢𝓸𝓾𝓻𝓬𝓮 𝓒𝓸𝓭𝓮𝓼", b"src_code_menu", "success", icon=5409320020058584473)],
        [style_btn("🛒 𝓑𝓾𝔂 𝓟𝓪𝓷𝓮𝓵𝓼", b"panels_menu", "success", icon=5409098988156629257)],
        [style_btn("🖥 𝓢𝓮𝓻𝓿𝓮𝓻𝓼", b"servers_menu", "primary", icon=5409119256107297715)],
        [style_btn("📦 𝓜𝓸𝓻𝓮 𝓒𝓸𝓷𝓽𝓮𝓷𝓽", b"more_content", "primary", icon=5409320020058584473)],
        [style_btn("💳 𝓡𝓮𝓬𝓱𝓪𝓻𝓰𝓮", b"open_deposit_menu", "primary", icon=5409271925014801629), style_btn("🧙 𝓟𝓻𝓸𝓯𝓲𝓵𝓮", b"profile_stats", "primary", icon=6203982793379154737)],
        [style_btn("⚙️ 𝓢𝓮𝓽𝓽𝓲𝓷𝓰𝓼", b"settings_menu", "primary", icon=5408995930416362034), style_url("📑 𝓕𝓮𝓮𝓭𝓫𝓪𝓬𝓴 ↗️", feedback_link, "primary", icon=6129732880529628243)],
        [style_btn("🆘 𝐇𝐞𝐥𝐩 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬", b"help_main", "success", icon=6129732880529628243)],
    ]
    
    edit_id = event.message_id if isinstance(event, events.CallbackQuery.Event) else None
    await send_preview_on_top(bot, uid, msg, start_img, buttons=buttons, edit_msg_id=edit_id)


def register_start(bot):
    @bot.on(events.CallbackQuery(pattern=r"^(dashboard_main|back_to_dashboard)$"))
    async def cb_dashboard_main(e):
        await send_main_menu(bot, e, e.sender_id)

    @bot.on(events.NewMessage(pattern=r"(?i)^(/start|🏠 𝐒ᴛᴀʀᴛ)"))
    async def handle_start(e):
        try:
            uid = e.sender_id
            if not uid: return
            
            is_new = cur.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is None
            
            ensure_user(uid)
            if is_user_banned(uid): return

            if not is_bot_online() and not is_admin(uid):
                return await e.respond(f"{P_OFF} <b>Bot is currently under maintenance.</b> Please try again later.")
            
            session_buy_state.pop(uid, None)
            deposit_input.pop(uid, None)

            text = e.text or ''
            if len(text.split()) > 1:
                start_param = text.split()[1]
                if start_param.startswith("ref_"):
                    ref = start_param.replace("ref_", "")
                    if ref.isdigit() and int(ref) != uid and is_new:
                        ref_exists = cur.execute("SELECT 1 FROM users WHERE user_id=?", (int(ref),)).fetchone()
                        if ref_exists:
                            cur.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL", (int(ref), uid))
                            db.commit()

            PFP_URL = "assets/image.jpg"
            is_joined = await check_channel_joined(bot, uid, is_admin)
            if not is_joined:
                from utils.helpers import get_unjoined_channels
                from telethon import Button
                from utils.keyboards import style_btn
                
                unjoined = await get_unjoined_channels(bot, uid)
                remaining = len(unjoined)
                msg = f"<blockquote>{PE_FLOWER} <b>𝐘ᴏᴜ ᴍᴜsᴛ ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟs & ɢʀᴏᴜᴘ ғɪʀsᴛ!</b></blockquote>\n<blockquote>{PE_LOCATION} {remaining} ᴄʜᴀɴɴᴇʟ(s)/ɢʀᴏᴜᴘ(s) ʀᴇᴍᴀɪɴɪɴɢ. 𝐉ᴏɪɴ ᴀɴᴅ ᴛᴀᴘ <b>𝐕ᴇʀɪғʏ 𝐉ᴏɪɴᴇᴅ</b>.</blockquote>"
                
                buttons = []
                for url, idx in unjoined:
                    btn_label = "💬 𝐉ᴏɪɴ 𝐆ʀᴏᴜᴘ" if ("+" in url or "joinchat" in url or idx == 2) else "📢 𝐉ᴏɪɴ 𝐂ʜᴀɴɴᴇʟ"
                    buttons.append([Button.url(btn_label, url)])
                buttons.append([style_btn("𝐕ᴇʀɪғʏ 𝐉ᴏɪɴᴇᴅ", b"verify_join", "success", icon=6129627894349045589)])
                
                try:
                    f = await bot.upload_file(PFP_URL)
                    media = types.InputMediaUploadedPhoto(file=f, spoiler=True)
                    return await bot.send_file(e.chat_id, media, caption=msg, buttons=buttons)
                except Exception as up_err:
                    logger.warning(f"Could not send photo banner: {up_err}, falling back to text")
                    return await e.respond(msg, buttons=buttons)

            row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (uid,)).fetchone()
            terms_acc = row[0] if row else 0
            if not terms_acc:
                terms_message = get_terms_message()
                if terms_message is None:
                    return await e.respond("⚠️ Terms & Conditions are temporarily unavailable. Please try /start again later.")
                return await e.respond(terms_message, buttons=get_terms_buttons())

            # The old welcome sticker/emoji face has been removed on purpose:
            # /start now goes straight to the clean dashboard.
            await send_main_menu(bot, e, uid)
        except Exception as ex: 
            logger.error(f"Start Error: {ex}", exc_info=True)

    @bot.on(events.NewMessage(pattern=r"(?i)^(🔻 𝐂ʟᴏsᴇ|❌ 𝐇ɪᴅᴇ|/hide|/close)$"))
    async def handle_close_keyboard(e):
        await e.respond("🔽 <i>Keyboard closed. Tap /menu or /start anytime to reopen.</i>", buttons=Button.clear())

    @bot.on(events.NewMessage(pattern=r"(?i)^/menu$"))
    async def handle_menu_cmd(e):
        uid = e.sender_id
        if not uid: return
        await e.respond("✨ <i>Menu shortcuts opened below 👇</i>", buttons=get_persistent_menu(uid))

    @bot.on(events.NewMessage(pattern=r"(?i)^/setsticker$"))
    async def cmd_set_sticker(e):
        if not is_admin(e.sender_id): return
        await e.reply("🎨 <b>Send or forward any Sticker now!</b>\n<i>The bot will automatically save it as the official /start Welcome Sticker.</i>")

    @bot.on(events.NewMessage(func=lambda e: e.is_private and e.sticker and is_admin(e.sender_id)))
    async def on_admin_sticker_received(e):
        try:
            doc = e.media.document
            import json
            data = json.dumps({
                'id': doc.id,
                'access_hash': doc.access_hash,
                'file_reference': doc.file_reference.hex()
            })
            cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('start_sticker', ?)", (data,))
            db.commit()
            
            # Download locally as backup
            try:
                ext = '.tgs' if 'tgsticker' in (doc.mime_type or '') else ('.webm' if 'video' in (doc.mime_type or '') else '.webp')
                await e.download_media(file=f"assets/start_sticker{ext}")
            except Exception as d_err:
                logger.warning(f"Could not download sticker locally: {d_err}")
                
            await e.reply("✅ <b>Start Welcome Sticker Updated Successfully!</b>\n\n<i>This sticker will now appear automatically on /start with the bottom reply keyboard.</i>")
        except Exception as ex:
            logger.error(f"Save sticker error: {ex}", exc_info=True)
            await e.reply("❌ Failed to save sticker.")

