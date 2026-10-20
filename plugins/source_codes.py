filename="source_codes.py"
import html
import os
import asyncio
from telethon import events, Button
from telethon.errors import MessageNotModifiedError, FloodWaitError
from database import cur, db, get_source_codes, is_admin
from utils.states import get_user_lock
from config import P_INR, P_NO, PE_CHECK, PE_GIFT, logger
from utils.keyboards import style_btn

# --- PREMIUM EMOJI DICTIONARY ---
EMOJIS = {
 "star": "⭐",
 "diamond": "💎",
 "fire": "🔥",
 "diamonds": "💠",
 "box": "📦",
 "rocket": "🚀",
 "check": "✅",
 "cross": "❌",
 "money": "💰",
 "heart": "❤️"
}

async def show_source_codes_menu(event):
 codes = get_source_codes()
 btns = []
 
 # Header with Premium Emoji
 msg = (f"<blockquote>{EMOJIS['diamonds']} <b>❄️ 𝐏ʀᴇᴍɪᴜᴍ 𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇ 𝐒ᴛᴏʀᴇ ❄️</b>\n"
 "───────────────────────────────\n"
 f"{EMOJIS['box']} <b>𝐒𝐭𝐨𝐜𝐤 𝐂𝐨𝐝𝐞𝐬:</b> {len(codes)}\n\n"
 f"{EMOJIS['star']} <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐭𝐡𝐞 𝐜𝐨𝐝𝐞 𝐲𝐨ᴜ ᴡᴀɴɴᴀ ʙᴜʏ:</b></blockquote>")
 
 for c_id, title, desc, price, file_path, avail in codes:
 # Format price nicely
 btns.append([style_btn(f"{EMOJIS['diamond']} {title} | {P_INR}{price}", f"src_info|{c_id}", "primary")])
 
 btns.append([style_btn(f"{EMOJIS['cross']} 🏃 𝐁ᴀᴄᴋ ᴛᴏ 𝐃ᴀsʜʙᴏᴀʀᴅ", b"dashboard_main", "danger", icon=6129812419028982717)])
 
 if isinstance(event, events.CallbackQuery.Event):
 try: await event.edit(msg, buttons=btns)
 except MessageNotModifiedError: pass
 else:
 await event.respond(msg, buttons=btns)

async def show_source_code_info(event, code_id):
 # Updated query to fetch file_path for ZIP delivery
 row = cur.execute("SELECT id, title, description, price, file_path FROM source_codes WHERE id=?", (code_id,)).fetchone()
 if not row:
 return await event.answer("❌ Source code not found.", alert=True)
 
 c_id, title, desc, price, file_path = row
 
 msg = (f"<blockquote>{EMOJIS['box']} <b>📦 {html.escape(title)}</b>\n\n"
 f"{EMOJIS['star']} <b>📝 𝐃ᴇsᴄʀɪᴘᴛɪᴏɴ:</b>\n{html.escape(desc)}\n\n"
 f"{EMOJIS['money']} <b>💰 𝐏ʀɪᴄᴇ:</b> <code>{P_INR}{price}</code>\n"
 f"{EMOJIS['rocket']} <b>⚡ 𝐃ᴇʟɪᴠᴇʀʏ:</b> <code>Direct ZIP File</code>\n\n"
 f"<b>𝐀ʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙᴜʏ?</b></blockquote>")
 
 btns = [
 [style_btn(f"{EMOJIS['check']} ✅ 𝐂ᴏɴғɪʀᴍ 𝐁ᴜʏ", f"src_cf|{c_id}", "success", icon=5409320020058584473)],
 [style_btn(f"{EMOJIS['cross']} 🏃 𝐁ᴀᴄᴋ", b"src_code_menu", "danger", icon=6129812419028982717)]
 ]
 try: await event.edit(msg, buttons=btns)
 except MessageNotModifiedError: pass

# --- ADMIN COMMAND TO ADD SOURCE CODE ---
async def add_source_code_handler(event):
 # Check if admin
 if not is_admin(event.sender_id):
 return await event.respond("❌ You are not authorized to add source codes.")

 # Parse command: /addcode <price> <title>
 # Example: /addcode 500 "My Bot"
 args = event.message.message.split(maxsplit=2)
 if len(args) < 3:
 return await event.respond("📝 Usage: /addcode <price> <title>\n\nExample: /addcode 500 Premium Bot")

 try:
 price = int(args[1])
 title = args[2]
 except ValueError:
 return await event.respond("❌ Please enter a valid number for the price.")

 # Check if file is attached
 if not event.message.media:
 return await event.respond("❌ Please attach a ZIP file with the source code.")

 # --- HANDLE FOLDER CREATION ---
 folder = "downloads"
 if not os.path.exists(folder):
 os.makedirs(folder)
 logger.info(f"Created folder: {folder}")

 # Save the file to local storage
 # Naming: download_{unique_id}.zip
 filename = f"download_{event.message.id}.zip"
 file_path = os.path.join(folder, filename)
 
 try:
 # Download the file
 downloaded = await event.client.download_media(event.message, file_path)
 logger.info(f"Downloaded source code: {downloaded}")
 except Exception as e:
 logger.error(f"Error downloading file: {e}")
 return await event.respond("❌ Failed to download the file. Please try again.")

 # Insert into database
 # Assuming table structure: source_codes(id, title, description, price, file_path, avail)
 cur.execute("INSERT INTO source_codes (title, description, price, file_path, avail) VALUES (?, ?, ?, ?, 1)", 
 (title, f"Premium source code by Admin.", price, file_path))
 db.commit()
 
 await event.respond(f"✅ <b>Source Code Added Successfully!</b>\n"
 f"🏷️ <b>Title:</b> {title}\n"
 f"💰 <b>Price:</b> {P_INR}{price}\n"
 f"📦 <b>File:</b> Saved to Database")

def register_source_codes(bot):
 @bot.on(events.NewMessage(pattern=r"^/addcode (\d+) (.+)"))
 async def cmd_add_code(e):
 await add_source_code_handler(e)
 
 @bot.on(events.CallbackQuery(pattern=b"^src_code_menu$"))
 async def cb_src_main(e):
 await show_source_codes_menu(e)
 
 @bot.on(events.CallbackQuery(pattern=r"^src_info\|(\d+)$"))
 async def cb_src_info(e):
 code_id = int(e.pattern_match.group(1).decode())
 await show_source_code_info(e, code_id)
 
 @bot.on(events.CallbackQuery(pattern=r"^src_cf\|(\d+)$"))
 async def cb_src_cf(e):
 uid = e.sender_id
 code_id = int(e.pattern_match.group(1).decode())
 
 row = cur.execute("SELECT id, title, description, price, file_path FROM source_codes WHERE id=?", (code_id,)).fetchone()
 if not row:
 return await e.answer("❌ Source code not found.", alert=True)
 
 c_id, title, desc, price, file_path = row
 
 async with get_user_lock(uid):
 bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
 if not bal_row or bal_row[0] < price:
 return await e.answer(f"❌ Insufficient Balance! Price: {P_INR}{price}, Your Balance: {P_INR}{bal_row[0] if bal_row else 0}", alert=True)
 
 cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (price, uid, price))
 db.commit()
 
 # Log to admin channels
 from database import get_log_channels_db
 for ch in get_log_channels_db():
 try:
 admin_log = (f"<blockquote>{PE_CHECK} <b>💻 𝐍ᴇᴡ 𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇ 𝐏ᴜʀᴄʜᴀsᴇ</b>\n\n"
 f"👤 <b>𝐔sᴇʀ:</b> <code>{uid}</code>\n"
 f"🏷️ <b>𝐈ᴛᴇᴍ:</b> {html.escape(title)}\n"
 f"💰 <b>𝐏ʀɪᴄᴇ:</b> {P_INR}{price}</blockquote>")
 await bot.send_message(ch, admin_log)
 except: pass
 
 msg = (f"<blockquote>{PE_CHECK} <b>🎉 𝐏ᴜʀᴄʜᴀsᴇ 𝐒ᴜᴄᴄᴇssғᴜʟ!</b>\n\n"
 f"{EMOJIS['star']} <b>💻 𝐈ᴛᴇᴍ:</b> <b>{html.escape(title)}</b>\n"
 f"{EMOJIS['money']} <b>𝐀ᴍᴏᴜɴᴛ 𝐏ᴀɪᴅ:</b> <code>{P_INR}{price}</code>\n\n"
 f"⚡ <b>Preparing PayPal...</b></blockquote>")
 
 await e.edit(msg)
 
 # DELIVER ZIP FILE DIRECTLY TO USER
 # 1. Wait a second to show success message
 await asyncio.sleep(1)
 
 try:
 await event.client.send_file(uid, file_path, caption=f"📦 <b>Here is your ZIP file:</b>\n{title}\n\nEnjoy your purchase! 🚀")
 
 except Exception as err:
 logger.error(f"Error sending file to {uid}: {err}")
 await e.edit(f"❌ Error sending file: {err}")
