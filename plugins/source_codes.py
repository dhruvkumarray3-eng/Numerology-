import html
import io
import re
import zipfile
from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db, get_source_codes, is_admin
from utils.states import get_user_lock
from config import P_INR, P_NO, PE_CHECK, PE_GIFT, logger
from utils.keyboards import style_btn


def _slugify(text):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (text or "source-code")).strip("-").lower()
    return slug or "source-code"


def _build_source_zip(title, file_content):
    """Package a source-code entry into an in-memory .zip archive.

    ``file_content`` may be a raw code/text blob or a download URL. Either way
    the buyer gets a real .zip document they can save and open.
    """
    content = (file_content or "").strip()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if content.lower().startswith(("http://", "https://")):
            readme = (
                f"{title}\n"
                f"{'=' * len(title)}\n\n"
                "Download / access link:\n"
                f"{content}\n\n"
                "Open the link above to fetch the source code archive.\n"
            )
            zf.writestr("README.txt", readme)
            zf.writestr("download-link.txt", content + "\n")
        else:
            safe = _slugify(title)
            zf.writestr(f"{safe}.txt", content if content else "// empty source code\n")
    buf.seek(0)
    return buf


async def show_source_codes_menu(event):
    codes = get_source_codes()
    btns = []
    for c_id, title, desc, price, file_link, avail in codes:
        btns.append([style_btn(f"{title} - {P_INR}{price}", f"src_info|{c_id}", "primary", icon="code")])
        
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐃ᴀsʜʙᴏᴀʀᴅ", b"dashboard_main", "danger", icon=6129812419028982717)])
    
    msg = ("<blockquote>💻 <b>𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇ 𝐒ᴛᴏʀᴇ</b>\n"
           "───────────────────────────────\n"
           "• 𝐑ᴇᴀᴅʏᴍᴀᴅᴇ ᴄᴏᴅᴇs, 𝐂ʀᴇᴀᴛᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛs\n"
           "• 𝐀ʟʟ ᴛʜɪɴɢs ᴀʀᴇ ᴅᴏɴᴇ ᴀʟʀᴇᴀᴅʏ ʏᴏᴜ ᴊᴜsᴛ ʜᴀᴠᴇ ᴛᴏ ᴇᴅɪᴛ ᴛʜᴇ ᴅᴇᴛᴀɪʟs\n\n"
           "<i>𝐒ᴇʟᴇᴄᴛ ᴛʜᴇ sᴏᴜʀᴄᴇ ᴄᴏᴅᴇ ʏᴏᴜ ᴡᴀɴɴᴀ ʙᴜʏ:</i></blockquote>")
           
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

async def show_source_code_info(event, code_id):
    row = cur.execute("SELECT id, title, description, price, file_content FROM source_codes WHERE id=?", (code_id,)).fetchone()
    if not row:
        return await event.answer("❌ Source code not found.", alert=True)
        
    c_id, title, desc, price, file_link = row
    msg = (f"<blockquote>💻 <b>{html.escape(title)}</b>\n\n"
           f"📝 <b>𝐃ᴇsᴄʀɪᴘᴛɪᴏɴ:</b>\n{html.escape(desc)}\n\n"
           f"💰 <b>𝐏ʀɪᴄᴇ:</b> <code>{P_INR}{price}</code>\n"
           f"⚡ <b>𝐃ᴇʟɪᴠᴇʀʏ:</b> <code>Instant Download Link</code>\n\n"
           f"<b>𝐀ʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙᴜʏ?</b></blockquote>")
           
    btns = [
        [style_btn("✅ 𝐂ᴏɴғɪʀᴍ 𝐁ᴜʏ", f"src_cf|{c_id}", "success", icon="buy")],
        [style_btn("🔙 𝐁ᴀᴄᴋ", b"src_code_menu", "danger", icon=6129812419028982717)]
    ]
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

def register_source_codes(bot):
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
        
        row = cur.execute("SELECT id, title, description, price, file_content FROM source_codes WHERE id=?", (code_id,)).fetchone()
        if not row:
            return await e.answer("❌ Source code not found.", alert=True)
            
        c_id, title, desc, price, file_link = row
        
        async with get_user_lock(uid):
            bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
            if not bal_row or bal_row[0] < price:
                return await e.answer(f"❌ Insufficient Balance! Price: ₹{price}, Your Balance: ₹{bal_row[0] if bal_row else 0}", alert=True)
                
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (price, uid, price))
            db.commit()
            
        from database import get_log_channels_db
        for ch in get_log_channels_db():
            try:
                admin_log = (f"<blockquote><b>💻 𝐍ᴇᴡ 𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇ 𝐏ᴜʀᴄʜᴀsᴇ</b>\n\n"
                             f"👤 <b>𝐔sᴇʀ:</b> <code>{uid}</code>\n"
                             f"🏷️ <b>𝐈ᴛᴇᴍ:</b> {html.escape(title)}\n"
                             f"💰 <b>𝐏ʀɪᴄᴇ:</b> {P_INR}{price}</blockquote>")
                await bot.send_message(ch, admin_log)
            except: pass
            
        safe_name = _slugify(title)
        # Owner-uploaded ZIP is stored as "file:<path>" -> deliver it as-is.
        stored_zip = None
        if (file_link or "").startswith("file:"):
            stored_zip = file_link.split(":", 1)[1].strip()
        zip_buf = None if stored_zip else _build_source_zip(title, file_link)

        msg = (
            f"<blockquote>{PE_CHECK} <b>\U0001F389 Purchase Successful!</b>\n\n"
            f"\U0001F4BB <b>Item:</b> <b>{html.escape(title)}</b>\n"
            f"\U0001F4B0 <b>Amount Paid:</b> <code>{P_INR}{price}</code>\n\n"
            f"\U0001F4E6 <b>Delivery:</b> ZIP file is sent below \u2b07\ufe0f\n"
            f"<i>Thank you for your purchase \u2014 extract the ZIP to get your files.</i>"
            f"</blockquote>"
        )

        btns = [
            [style_btn("\U0001F519 Back to Store", b"src_code_menu", "primary", icon=6129812419028982717)]
        ]
        try:
            await e.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass

        # Deliver the real ZIP document to the buyer
        try:
            await bot.send_file(
                e.chat_id,
                stored_zip if stored_zip else zip_buf,
                filename=f"{safe_name}.zip",
                caption=(
                    f"\U0001F4E6 <b>{html.escape(title)}</b>\n"
                    f"<i>Your source code ZIP \u2014 extract and open.</i>"
                ),
                force_document=True,
            )
        except Exception as _zip_ex:
            logger.warning(f"source zip send failed: {_zip_ex}")
            try:
                await e.respond(
                    f"\U0001F517 <b>Download link:</b> <code>{html.escape(file_link)}</code>"
                )
            except Exception:
                pass
        try:
            from utils import stickers as _sticker_engine
            await _sticker_engine.send_purchase_for_event(e)
        except Exception as _sk_ex:
            logger.debug(f"purchase emoji skipped: {_sk_ex}")
