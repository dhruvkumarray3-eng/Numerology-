"""Admin-only manager for the user-facing panel and source-code catalogs."""

import base64
import html
import io
import math
import zipfile
from urllib.parse import urlparse

from telethon import events
from telethon.errors import MessageNotModifiedError

from config import logger
from database import cur, db, get_panels, get_source_codes, has_perm
from utils.keyboards import style_btn

MAX_SOURCE_ZIP_BYTES = 20 * 1024 * 1024


def _can_manage(uid):
    try:
        return bool(has_perm(uid, "p_manage_stock"))
    except Exception:
        return False


async def _send(event, text, buttons):
    try:
        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)
    except MessageNotModifiedError:
        pass


async def show_catalog_manager(event):
    if not _can_manage(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)

    panels = get_panels()
    sources = get_source_codes()
    msg = (
        "<blockquote>🛍 <b>Product Catalog Manager</b>\n\n"
        f"Panels: <code>{len(panels)}</code>\n"
        f"Source-code ZIPs: <code>{len(sources)}</code>\n\n"
        "Add listings here. They appear to users only after the admin saves them.</blockquote>"
    )
    buttons = [
        [style_btn("➕ Add Panel Link", "adm_catalog_add_panel", "success")],
        [style_btn("➕ Add Source-Code ZIP", "adm_catalog_add_source", "primary")],
        [style_btn("🗑 Manage / Delete Listings", "ac_menu", "danger")],
        [style_btn("🔙 Back to Admin Panel", "adm_adminmain", "primary")],
    ]
    await _send(event, msg, buttons)


async def _next_text(conv, uid, prompt):
    await conv.send_message(prompt)
    reply = await conv.get_response()
    if reply.sender_id != uid:
        raise ValueError("Only the admin who started this action can answer.")
    text = (reply.raw_text or "").strip()
    if text.lower() in ("/cancel", "cancel"):
        return None
    if not text:
        raise ValueError("The value cannot be empty.")
    return text


def _parse_price(text):
    value = float(text.replace("₹", "").replace(",", "").strip())
    if not math.isfinite(value) or value < 0 or value > 10_000_000:
        raise ValueError("Enter a finite price between ₹0 and ₹10,000,000.")
    return value


def _validate_panel_url(text):
    url = text.strip()
    parsed = urlparse(url)
    if len(url) > 2000 or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a valid http:// or https:// panel link.")
    return url


async def _add_panel(event, bot):
    uid = event.sender_id
    if event.chat_id != uid:
        return await event.answer("Open the admin panel in a private chat to add a listing.", alert=True)
    await event.answer()
    await event.edit(
        "<blockquote>➕ <b>Add Panel Link</b>\n\n"
        "Send the title, price, and link when prompted. Send <code>/cancel</code> at any step to stop.</blockquote>"
    )
    try:
        async with bot.conversation(event.chat_id, timeout=300) as conv:
            title = await _next_text(conv, uid, "Send the panel title (up to 80 characters):")
            if title is None:
                await conv.send_message("Cancelled; nothing was added.")
                return await show_catalog_manager(event)
            if len(title) > 80:
                raise ValueError("Panel title must be 80 characters or fewer.")

            price_text = await _next_text(conv, uid, "Send the price in INR (example: 299):")
            if price_text is None:
                await conv.send_message("Cancelled; nothing was added.")
                return await show_catalog_manager(event)
            price = _parse_price(price_text)

            link_text = await _next_text(conv, uid, "Send the panel URL (https://…):")
            if link_text is None:
                await conv.send_message("Cancelled; nothing was added.")
                return await show_catalog_manager(event)
            link = _validate_panel_url(link_text)

            cur.execute(
                "INSERT INTO panels (title, description, price, panel_content, available) "
                "VALUES (?, ?, ?, ?, 1)",
                (title, "Panel access link", price, link),
            )
            db.commit()
            await conv.send_message(f"✅ Added <b>{html.escape(title)}</b> at ₹{price:g}.")
    except Exception as exc:
        logger.warning(f"Admin add panel flow failed: {exc}")
        try:
            await event.respond(f"❌ Panel was not added: <code>{html.escape(str(exc))}</code>")
        except Exception:
            pass
    await show_catalog_manager(event)


async def _add_source_zip(event, bot):
    uid = event.sender_id
    if event.chat_id != uid:
        return await event.answer("Open the admin panel in a private chat to add a listing.", alert=True)
    await event.answer()
    await event.edit(
        "<blockquote>➕ <b>Add Source-Code ZIP</b>\n\n"
        "Send the title, price, and ZIP file when prompted. Send <code>/cancel</code> at any step to stop.</blockquote>"
    )
    try:
        async with bot.conversation(event.chat_id, timeout=300) as conv:
            title = await _next_text(conv, uid, "Send the source-code title (up to 80 characters):")
            if title is None:
                await conv.send_message("Cancelled; nothing was added.")
                return await show_catalog_manager(event)
            if len(title) > 80:
                raise ValueError("Source-code title must be 80 characters or fewer.")

            price_text = await _next_text(conv, uid, "Send the price in INR (example: 299):")
            if price_text is None:
                await conv.send_message("Cancelled; nothing was added.")
                return await show_catalog_manager(event)
            price = _parse_price(price_text)

            await conv.send_message("Now upload the source-code archive as a ZIP document (maximum 20 MB).")
            upload = await conv.get_response()
            if upload.sender_id != uid:
                raise ValueError("Only the admin who started this action can upload the archive.")
            if not upload.document and (upload.raw_text or "").strip().lower() in ("/cancel", "cancel"):
                await conv.send_message("Cancelled; nothing was added.")
                return await show_catalog_manager(event)
            if not upload.document:
                raise ValueError("Please upload a ZIP document.")
            file_size = getattr(getattr(upload, "file", None), "size", None)
            if file_size is not None and file_size > MAX_SOURCE_ZIP_BYTES:
                raise ValueError("The ZIP file exceeds the 20 MB limit.")
            archive = await upload.download_media(bytes)
            if not archive or len(archive) > MAX_SOURCE_ZIP_BYTES:
                raise ValueError("Could not read the ZIP or it exceeds the 20 MB limit.")
            if not zipfile.is_zipfile(io.BytesIO(archive)):
                raise ValueError("The uploaded file is not a valid ZIP archive.")

            stored = "zip64:" + base64.b64encode(archive).decode("ascii")
            cur.execute(
                "INSERT INTO source_codes (title, description, price, file_content, available) "
                "VALUES (?, ?, ?, ?, 1)",
                (title, "Source-code ZIP archive", price, stored),
            )
            db.commit()
            await conv.send_message(f"✅ Added <b>{html.escape(title)}</b> at ₹{price:g}.")
    except Exception as exc:
        logger.warning(f"Admin add source ZIP flow failed: {exc}")
        try:
            await event.respond(f"❌ Source ZIP was not added: <code>{html.escape(str(exc))}</code>")
        except Exception:
            pass
    await show_catalog_manager(event)


def register_admin_catalogs(bot):
    @bot.on(events.CallbackQuery(pattern=r"^adm_catalogs$"))
    async def cb_catalogs(event):
        await show_catalog_manager(event)

    @bot.on(events.CallbackQuery(pattern=r"^adm_catalog_add_panel$"))
    async def cb_add_panel(event):
        if not _can_manage(event.sender_id):
            return await event.answer("⛔ Admin only.", alert=True)
        await _add_panel(event, bot)

    @bot.on(events.CallbackQuery(pattern=r"^adm_catalog_add_source$"))
    async def cb_add_source(event):
        if not _can_manage(event.sender_id):
            return await event.answer("⛔ Admin only.", alert=True)
        await _add_source_zip(event, bot)
