import html
import io
import base64
import re
import zipfile
from telethon import events
from telethon.errors import MessageNotModifiedError
from database import cur, db, get_source_codes
from utils.states import get_user_lock
from config import P_INR, PE_CHECK, logger
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


def _build_delivery_zip(title, file_content):
    """Return an uploaded ZIP or package a legacy text/URL catalog entry."""
    content = str(file_content or "")
    if content.startswith("zip64:"):
        try:
            raw = base64.b64decode(content[6:], validate=True)
        except Exception as exc:
            raise ValueError("Stored ZIP data is invalid") from exc
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            raise ValueError("Stored source archive is not a valid ZIP")
        return io.BytesIO(raw)
    return _build_source_zip(title, content)


async def show_source_codes_menu(event):
    codes = get_source_codes()
    btns = []
    for c_id, title, desc, price, file_link, avail, stock in codes:
        stock_label = f"📦 {int(stock)}" if int(stock or 0) > 0 else "🔴 OUT OF STOCK"
        btns.append([style_btn(f"{str(title)[:30]} - {P_INR}{price} · {stock_label}", f"src_info|{c_id}", "primary", icon="code")])
        
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐃ᴀsʜʙᴏᴀʀᴅ", b"dashboard_main", "danger", icon=6129812419028982717)])
    
    if codes:
        msg = ("<blockquote>💻 <b>𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇ 𝐒ᴛᴏʀᴇ</b>\n"
               "───────────────────────────────\n"
               "• Admin-listed ZIP archives with title and price\n\n"
               "<i>Select a source-code ZIP to view its details:</i></blockquote>")
    else:
        msg = ("<blockquote>💻 <b>𝐒ᴏᴜʀᴄᴇ 𝐂ᴏᴅᴇ 𝐒ᴛᴏʀᴇ</b>\n\n"
        "No source-code ZIPs are currently visible. Please check back later.</blockquote>")
           
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

async def show_source_code_info(event, code_id):
    row = cur.execute(
        "SELECT id, title, description, price, file_content, stock FROM source_codes "
        "WHERE id=? AND available=1", (code_id,)
    ).fetchone()
    if not row:
        return await event.answer("❌ Source code not found.", alert=True)
        
    c_id, title, desc, price, file_link, stock = row
    msg = (f"<blockquote>💻 <b>{html.escape(title)}</b>\n\n"
           f"📝 <b>𝐃ᴇsᴄʀɪᴘᴛɪᴏɴ:</b>\n{html.escape(desc)}\n\n"
           f"💰 <b>𝐏ʀɪᴄᴇ:</b> <code>{P_INR}{price}</code>\n"
           f"📦 <b>Stock:</b> <code>{int(stock or 0)}</code>\n"
           f"⚡ <b>𝐃ᴇʟɪᴠᴇʀʏ:</b> <code>ZIP file</code>\n\n"
           f"{('<b>Out of stock. Please contact the admin.</b>' if int(stock or 0) <= 0 else '<b>𝐀ʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙᴜʏ?</b>')}</blockquote>")
           
    btns = []
    if int(stock or 0) > 0:
        btns.append([style_btn("✅ 𝐂ᴏɴғɪʀᴍ 𝐁ᴜʏ", f"src_cf|{c_id}", "success", icon="buy")])
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ", b"src_code_menu", "danger", icon=6129812419028982717)])
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
        
        row = cur.execute(
            "SELECT id, title, description, price, file_content, stock FROM source_codes "
            "WHERE id=? AND available=1", (code_id,)
        ).fetchone()
        if not row:
            return await e.answer("❌ Source code not found.", alert=True)
            
        c_id, title, desc, price, file_link, stock = row
        if int(stock or 0) <= 0:
            return await e.answer("📦 This source ZIP is out of stock. Please contact the admin.", alert=True)

        safe_name = _slugify(title)
        stored_zip = None
        if (file_link or "").startswith("file:"):
            stored_zip = file_link.split(":", 1)[1].strip()
        try:
            zip_buf = None if stored_zip else _build_delivery_zip(title, file_link)
        except ValueError as exc:
            return await e.answer(f"❌ The source ZIP is unavailable: {html.escape(str(exc))}", alert=True)

        async with get_user_lock(uid):
            current = cur.execute(
                "SELECT stock, available FROM source_codes WHERE id=?", (c_id,)
            ).fetchone()
            bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
            if not current or not current[1] or int(current[0] or 0) <= 0:
                return await e.answer("📦 This source ZIP is out of stock. Please contact the admin.", alert=True)
            if not bal_row or bal_row[0] < price:
                return await e.answer(f"❌ Insufficient Balance! Price: ₹{price}, Your Balance: ₹{bal_row[0] if bal_row else 0}", alert=True)
            cur.execute(
                "UPDATE source_codes SET stock=stock-1 WHERE id=? AND available=1 AND stock>0",
                (c_id,),
            )
            if cur.rowcount != 1:
                db.rollback()
                return await e.answer("📦 This source ZIP is out of stock. Please contact the admin.", alert=True)
            cur.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                (price, uid, price),
            )
            if cur.rowcount != 1:
                db.rollback()
                return await e.answer("❌ Your balance changed. Please try the purchase again.", alert=True)
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
        except Exception as edit_ex:
            logger.warning(f"source purchase confirmation edit failed: {edit_ex}")

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
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (price, uid))
                cur.execute("UPDATE source_codes SET stock=stock+1 WHERE id=?", (c_id,))
                db.commit()
            try:
                await e.respond("❌ ZIP delivery failed; your balance was refunded and stock restored. Please contact the admin.")
            except Exception:
                pass
        try:
            from utils import stickers as _sticker_engine
            await _sticker_engine.send_purchase_for_event(e)
        except Exception as _sk_ex:
            logger.debug(f"purchase emoji skipped: {_sk_ex}")
