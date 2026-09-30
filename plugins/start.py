import html
from telethon import events, types, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db, ensure_user, is_user_banned, is_bot_online, is_admin, get_support_url, get_start_image_url
from utils.keyboards import get_persistent_menu, get_terms_buttons, get_join_buttons, style_btn, style_url
from utils.terms import get_terms_message
from utils.helpers import check_channel_joined, to_small_caps, send_preview_on_top
from config import PE_FLOWER, PE_LOCATION, P_OFF, P_INR, TERMS_URL, UPDATES_URL, logger
from utils.states import session_buy_state, deposit_input

async def send_start_sticker_or_menu(bot, uid):
    import os
    import json
    from utils.keyboards import get_persistent_menu
    
    # 1. Check if custom sticker is saved in database
    row = cur.execute("SELECT value FROM settings WHERE key='start_sticker'").fetchone()
    if row and row[0]:
        try:
            d = json.loads(row[0])
            doc = types.InputDocument(
                id=int(d['id']),
                access_hash=int(d['access_hash']),
                file_reference=bytes.fromhex(d['file_reference'])
            )
            return await bot.send_file(uid, doc, buttons=get_persistent_menu(uid))
        except Exception as ex:
            logger.warning(f"Failed to send saved sticker doc: {ex}")

    # 2. Check if local sticker asset exists
    for ext in ['.webp', '.tgs', '.webm']:
        local_p = f"assets/start_sticker{ext}"
        if os.path.exists(local_p):
            try:
                return await bot.send_file(uid, local_p, buttons=get_persistent_menu(uid))
            except Exception as ex:
                logger.warning(f"Failed to send local sticker {local_p}: {ex}")

    # 3. Fallback: send clean minimal emoji greeting with keyboard
    try:
        return await bot.send_message(uid, "👋", buttons=get_persistent_menu(uid))
    except Exception as ex:
        logger.warning(f"Fallback keyboard send failed: {ex}")

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
    
    update_link = UPDATES_URL
    feedback_link = support_url
    
    styled_name = to_small_caps(bot_name)
    
    msg = (f"<a href='{start_img}'>&#8203;</a>💬 <b>{html.escape(styled_name)}</b>\n\n"
           f"<blockquote expandable>"
           f"👥 <b>𝐍ᴀᴍᴇ:</b> {html.escape(first_name)}\n"
           f"🪪 <b>𝐔sᴇʀ 𝐈𝐃:</b> <code>{uid}</code>\n"
           f"🎯 <b>𝐔sᴇʀɴᴀᴍᴇ:</b> {username}\n"
           f"💳 <b>𝐁ᴀʟᴀɴᴄᴇ:</b> <code>₹{bal:.2f}</code>"
           f"</blockquote>\n"
           f"<blockquote>✈️ <b>𝐒ᴜᴘᴘᴏʀᴛ :</b> <a href='{support_url}'>{support_handle}</a></blockquote>")
           
    buttons = [
        [style_btn("📲 𝐁ᴜʏ 𝐀ᴄᴄᴏᴜɴᴛ", b"open_buy_categories", "success", icon=5440627033111557670)],
        [style_btn("🚀 𝐒ᴏᴄɪᴀʟ ᴍᴇᴅɪᴀ sᴇʀᴠɪᴄᴇs", b"smm_menu_main", "success", icon=5408995930416362034)],
        [style_btn("🛒 𝐁ᴜʏ 𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇs", b"src_code_menu", "success", icon=5409320020058584473)],
        [style_btn("🛒 𝐁ᴜʏ 𝐏ᴀɴᴇʟs", b"panels_menu", "success", icon=5409098988156629257)],
        [style_url("💬 𝐎ᴛʜᴇʀ 𝐂ᴏɴᴛᴇɴᴛ ↗️", update_link, "danger", icon=6129812419028982717)],
        [style_btn("💳 𝐑ᴇᴄʜᴀʀɢᴇ", b"open_deposit_menu", "primary", icon=5409271925014801629), style_btn("🧙 𝐏ʀᴏғɪʟᴇ", b"profile_stats", "primary", icon=6203982793379154737)],
        [style_btn("💬 𝐌ᴏʀᴇ", b"more_menu", "primary", icon=6129627894349045589), style_url("📑 𝐅ᴇᴇᴅʙᴀᴄᴋ ↗️", feedback_link, "primary", icon=6129732880529628243)]
    ]
    
    edit_id = event.message_id if isinstance(event, events.CallbackQuery.Event) else None
    await send_preview_on_top(bot, uid, msg, start_img, buttons=buttons, edit_msg_id=edit_id)


def register_start(bot):
    @bot.on(events.CallbackQuery(pattern=r"^(dashboard_main|back_to_dashboard|buy_menu_main)$"))
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

            try:
                await send_start_sticker_or_menu(bot, uid)
            except Exception as k_err:
                logger.warning(f"Could not send start sticker: {k_err}")

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

