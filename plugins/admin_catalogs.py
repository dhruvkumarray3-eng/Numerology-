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
from database import cur, db, has_perm
from utils.keyboards import style_btn, pe

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

    panels_total = cur.execute("SELECT COUNT(*) FROM panels").fetchone()[0]
    sources_total = cur.execute("SELECT COUNT(*) FROM source_codes").fetchone()[0]
    panels_visible = cur.execute("SELECT COUNT(*) FROM panels WHERE available=1").fetchone()[0]
    sources_visible = cur.execute("SELECT COUNT(*) FROM source_codes WHERE available=1").fetchone()[0]
    msg = (
        f"<blockquote>{pe('panel', '🛍')} <b>𝗣𝗿𝗼𝗱𝘂𝗰𝘁 𝗖𝗮𝘁𝗮𝗹𝗼𝗴 𝗠𝗮𝗻𝗮𝗴𝗲𝗿</b>\n\n"
        f"🌐 <b>Panels:</b> <code>{panels_visible}/{panels_total}</code> visible\n"
        f"💻 <b>Source ZIPs:</b> <code>{sources_visible}/{sources_total}</code> visible\n"
        "📦 New listings start with stock <code>0</code>. Add stock before users can buy.\n"
        "👁 Listings can be hidden or shown at any time.</blockquote>"
    )
    buttons = [
        [style_btn("➕ Add Panel Link", "adm_catalog_add_panel", "success", icon="panel")],
        [style_btn("➕ Add Source-Code ZIP", "adm_catalog_add_source", "primary", icon="source")],
        [style_btn("👁 Manage Panel Visibility / Stock", "adm_catalog_manage|panel", "primary", icon="panel")],
        [style_btn("👁 Manage ZIP Visibility / Stock", "adm_catalog_manage|source", "success", icon="source")],
        [style_btn("🗑 Manage / Delete Listings", "ac_menu", "danger", icon="delete")],
        [style_btn("🔙 Back to Admin Panel", "adm_adminmain", "primary", icon="back")],
    ]
    await _send(event, msg, buttons)


def _catalog_spec(kind):
    if kind == "panel":
        return "panels", "panel_content", "Panel"
    if kind == "source":
        return "source_codes", "file_content", "Source ZIP"
    raise ValueError("Unknown catalog type")


async def _show_catalog_items(event, kind):
    if not _can_manage(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    table, _content_column, title = _catalog_spec(kind)
    rows = cur.execute(
        f"SELECT id, title, price, available, stock FROM {table} ORDER BY id DESC"
    ).fetchall()
    visible = sum(1 for _i, _t, _p, active, _s in rows if active)
    msg = (
        f"<blockquote>{pe('stock', '📦')} <b>𝗠𝗮𝗻𝗮𝗴𝗲 {title} Listings</b>\n\n"
        f"👁 Visible: <code>{visible}</code> · Hidden: <code>{len(rows) - visible}</code>\n"
        "A hidden item does not appear in the user store. Stock 0 is out of stock.</blockquote>"
    )
    buttons = []
    for item_id, item_title, price, active, stock in rows[:30]:
        verb = "🙈 Hide" if active else "👁 Show"
        style = "danger" if active else "success"
        safe_title = str(item_title or "Untitled")[:22]
        buttons.append([
            style_btn(f"{verb} · #{item_id} {safe_title} · ₹{float(price or 0):g}",
                      f"adm_catalog_toggle|{kind}|{item_id}", style,
                      icon="close" if active else "check"),
            style_btn(f"📦 Stock {int(stock)}", f"adm_catalog_stock|{kind}|{item_id}",
                      "primary", icon="stock"),
        ])
    if len(rows) > 30:
        msg += "\n<i>Showing the latest 30 listings.</i>"
    buttons.append([style_btn("🔙 Catalog Manager", "adm_catalogs", "primary", icon="back")])
    await _send(event, msg, buttons)


async def _toggle_catalog_visibility(event, kind, item_id):
    if not _can_manage(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    table, _content_column, title = _catalog_spec(kind)
    row = cur.execute(f"SELECT title, available FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row:
        return await event.answer(f"{title} listing not found.", alert=True)
    new_visibility = 0 if row[1] else 1
    cur.execute(f"UPDATE {table} SET available=? WHERE id=?", (new_visibility, item_id))
    db.commit()
    state = "visible to users" if new_visibility else "hidden from users"
    await event.answer(f"✅ {row[0]} is now {state}.")
    await _show_catalog_items(event, kind)


async def _set_catalog_stock(event, bot, kind, item_id):
    if not _can_manage(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    uid = event.sender_id
    if event.chat_id != uid:
        return await event.answer("Open this control in a private chat to set stock.", alert=True)
    table, _content_column, title = _catalog_spec(kind)
    row = cur.execute(f"SELECT title, stock FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row:
        return await event.answer(f"{title} listing not found.", alert=True)
    await event.answer()
    await event.edit(
        f"<blockquote>📦 <b>Set {title} Stock</b>\n"
        f"{html.escape(str(row[0]))}\nCurrent stock: <code>{int(row[1])}</code>\n\n"
        "Send the new whole-number stock amount (0–100000). Use <code>/cancel</code> to stop.</blockquote>"
    )
    try:
        async with bot.conversation(event.chat_id, timeout=180) as conv:
            await conv.send_message("Send the new stock amount:")
            reply = await conv.get_response()
            if reply.sender_id != uid:
                raise ValueError("Only the admin who started this action can answer.")
            text = (reply.raw_text or "").strip().lower()
            if text in ("/cancel", "cancel"):
                await conv.send_message("Cancelled; stock was not changed.")
                return await _show_catalog_items(event, kind)
            if not text.isdigit() or int(text) > 100_000:
                raise ValueError("Enter a whole number from 0 to 100000.")
            cur.execute(f"UPDATE {table} SET stock=? WHERE id=?", (int(text), item_id))
            db.commit()
            await conv.send_message(f"✅ Stock for <b>{html.escape(str(row[0]))}</b> set to <code>{int(text)}</code>.")
    except Exception as exc:
        logger.warning(f"Admin catalog stock update failed: {exc}")
        try:
            await event.respond(f"❌ Stock was not changed: <code>{html.escape(str(exc))}</code>")
        except Exception:
            pass
    await _show_catalog_items(event, kind)


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
                "INSERT INTO panels (title, description, price, panel_content, available, stock) "
                "VALUES (?, ?, ?, ?, 1, 0)",
                (title, "Panel access link", price, link),
            )
            db.commit()
            await conv.send_message(
                f"✅ Added <b>{html.escape(title)}</b> at ₹{price:g}. "
                "It is visible to users with stock 0; set stock in Catalog Manager before sales."
            )
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
                "INSERT INTO source_codes (title, description, price, file_content, available, stock) "
                "VALUES (?, ?, ?, ?, 1, 0)",
                (title, "Source-code ZIP archive", price, stored),
            )
            db.commit()
            await conv.send_message(
                f"✅ Added <b>{html.escape(title)}</b> at ₹{price:g}. "
                "It is visible to users with stock 0; set stock in Catalog Manager before sales."
            )
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

    @bot.on(events.CallbackQuery(pattern=r"^adm_catalog_manage\|(panel|source)$"))
    async def cb_catalog_manage(event):
        await _show_catalog_items(event, event.pattern_match.group(1).decode())

    @bot.on(events.CallbackQuery(pattern=r"^adm_catalog_toggle\|(panel|source)\|(\d+)$"))
    async def cb_catalog_toggle(event):
        kind = event.pattern_match.group(1).decode()
        item_id = int(event.pattern_match.group(2).decode())
        await _toggle_catalog_visibility(event, kind, item_id)

    @bot.on(events.CallbackQuery(pattern=r"^adm_catalog_stock\|(panel|source)\|(\d+)$"))
    async def cb_catalog_stock(event):
        kind = event.pattern_match.group(1).decode()
        item_id = int(event.pattern_match.group(2).decode())
        await _set_catalog_stock(event, bot, kind, item_id)

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
