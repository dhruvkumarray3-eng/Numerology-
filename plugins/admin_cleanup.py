"""Admin cleanup & delete systems.

Reachable from BOTH admin panel entry points (the /admin panel and the
admin /help card).  Provides safe, confirmed deletion of:

  * old account stock        (older than N days)
  * sold / unavailable stock
  * ALL stock
  * individual panels / all panels
  * individual source codes / all source codes

Every destructive action requires a second confirmation tap.
"""

import html

from telethon import events
from telethon.errors import MessageNotModifiedError

from config import logger
from database import cur, db, is_admin, has_perm
from utils.keyboards import style_btn, pe


def _can(uid):
    try:
        return bool(is_admin(uid)) or bool(has_perm(uid, "p_manage_stock"))
    except Exception:
        try:
            return bool(is_admin(uid))
        except Exception:
            return False


def _counts():
    def _one(sql):
        try:
            return cur.execute(sql).fetchone()[0]
        except Exception:
            return 0
    return {
        "total": _one("SELECT COUNT(*) FROM stock"),
        "avail": _one("SELECT COUNT(*) FROM stock WHERE available=1"),
        "sold": _one("SELECT COUNT(*) FROM stock WHERE available=0"),
        "panels": _one("SELECT COUNT(*) FROM panels"),
        "src": _one("SELECT COUNT(*) FROM source_codes"),
    }


async def _send(event, text, buttons):
    try:
        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)
    except MessageNotModifiedError:
        pass


async def show_cleanup_menu(event):
    if not _can(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    c = _counts()
    msg = (
        f"<blockquote>{pe('cleanup', '🗑')} <b>𝗖𝗹𝗲𝗮𝗻𝘂𝗽 & 𝗗𝗲𝗹𝗲𝘁𝗲 𝗖𝗲𝗻𝘁𝗲𝗿</b>\n\n"
        f"📦 <b>Total Stock:</b> <code>{c['total']}</code> "
        f"(available <code>{c['avail']}</code> · sold <code>{c['sold']}</code>)\n"
        f"🗂 <b>Panels:</b> <code>{c['panels']}</code>\n"
        f"💻 <b>Source Codes:</b> <code>{c['src']}</code>\n\n"
        f"<i>Every delete asks for a confirmation first.</i></blockquote>"
    )
    btns = [
        [style_btn("🗑 Delete Old Stock", "ac_stock_old_menu", "danger", icon="delete")],
        [style_btn("🧹 Delete Sold / Unavailable Stock", "ac_confirm|stock_sold", "danger", icon="delete")],
        [style_btn("🧨 Delete ALL Stock", "ac_confirm|stock_all", "danger", icon="delete")],
        [style_btn(f"🗂 Manage / Delete Panels ({c['panels']})", "ac_panels", "primary", icon="panel")],
        [style_btn(f"💻 Manage / Delete Source Codes ({c['src']})", "ac_src", "primary", icon="code")],
        [style_btn("🔙 Back to Admin Panel", "adm_adminmain", "success", icon="back")],
    ]
    await _send(event, msg, btns)


async def show_old_stock_menu(event):
    if not _can(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    msg = (
        f"<blockquote>{pe('delete', '🗑')} <b>𝗗𝗲𝗹𝗲𝘁𝗲 𝗢𝗹𝗱 𝗦𝘁𝗼𝗰𝗸</b>\n\n"
        f"Choose how old the accounts must be before deletion. "
        f"Only rows older than the selected age are removed.</blockquote>"
    )
    btns = [
        [style_btn("7 days old", "ac_confirm|stock_old|7", "danger", icon="delete"),
         style_btn("30 days old", "ac_confirm|stock_old|30", "danger", icon="delete")],
        [style_btn("90 days old", "ac_confirm|stock_old|90", "danger", icon="delete"),
         style_btn("365 days old", "ac_confirm|stock_old|365", "danger", icon="delete")],
        [style_btn("🔙 Back", "ac_menu", "primary", icon="back")],
    ]
    await _send(event, msg, btns)


async def show_panels(event):
    if not _can(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    rows = cur.execute("SELECT id, title, price FROM panels ORDER BY id DESC").fetchall()
    btns = []
    for pid, title, price in rows[:30]:
        label = f"🗑 #{pid} · {str(title)[:24]}"
        btns.append([style_btn(label, f"ac_panel_del|{pid}", "danger", icon="delete")])
    if rows:
        btns.append([style_btn(f"🧨 Delete ALL Panels ({len(rows)})", "ac_confirm|panels_all", "danger", icon="delete")])
    btns.append([style_btn("🔙 Back", "ac_menu", "primary", icon="back")])
    msg = (
        f"<blockquote>{pe('panel', '🗂')} <b>𝗠𝗮𝗻𝗮𝗴𝗲 𝗣𝗮𝗻𝗲𝗹𝘀</b>\n\n"
        f"Tap a panel to delete it permanently. Total: <code>{len(rows)}</code></blockquote>"
    )
    await _send(event, msg, btns)


async def show_sources(event):
    if not _can(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    rows = cur.execute("SELECT id, title, price FROM source_codes ORDER BY id DESC").fetchall()
    btns = []
    for sid, title, price in rows[:30]:
        label = f"🗑 #{sid} · {str(title)[:24]}"
        btns.append([style_btn(label, f"ac_src_del|{sid}", "danger", icon="delete")])
    if rows:
        btns.append([style_btn(f"🧨 Delete ALL Source Codes ({len(rows)})", "ac_confirm|src_all", "danger", icon="delete")])
    btns.append([style_btn("🔙 Back", "ac_menu", "primary", icon="back")])
    msg = (
        f"<blockquote>{pe('code', '💻')} <b>𝗠𝗮𝗻𝗮𝗴𝗲 𝗦𝗼𝘂𝗿𝗰𝗲 𝗖𝗼𝗱𝗲𝘀</b>\n\n"
        f"Tap an item to delete it permanently. Total: <code>{len(rows)}</code></blockquote>"
    )
    await _send(event, msg, btns)


async def _confirm(event, what, arg=None):
    labels = {
        "stock_sold": "delete ALL sold / unavailable stock",
        "stock_all": "delete ALL stock (every account)",
        "panels_all": "delete ALL panels",
        "src_all": "delete ALL source codes",
    }
    if what == "stock_old":
        try:
            n = cur.execute(
                "SELECT COUNT(*) FROM stock "
                "WHERE datetime(COALESCE(added_date, '1970-01-01')) "
                "< datetime('now', ?)",
                (f"-{int(arg or 7)} days",),
            ).fetchone()[0]
        except Exception:
            n = 0
        desc = f"delete stock older than {arg} days ({n} row(s))"
    else:
        desc = labels.get(what, what)
    msg = (
        f"<blockquote>⚠️ <b>𝗖𝗼𝗻𝗳𝗶𝗿𝗺 𝗗𝗲𝗹𝗲𝘁𝗶𝗼𝗻</b>\n\n"
        f"You are about to <b>{html.escape(desc)}</b>.\n\n"
        f"<i>This cannot be undone.</i></blockquote>"
    )
    cb = f"ac_do|{what}" + (f"|{arg}" if arg is not None else "")
    btns = [
        [style_btn("✅ Yes, delete now", cb, "danger", icon="delete")],
        [style_btn("❌ Cancel", "ac_menu", "success", icon="back")],
    ]
    await _send(event, msg, btns)


async def _execute(event, what, arg=None):
    if not _can(event.sender_id):
        return await event.answer("⛔ Admin only.", alert=True)
    removed = 0
    try:
        if what == "stock_old":
            days = int(arg or 7)
            # COALESCE handles rows with a NULL added_date (they are treated as
            # ancient and removed too).  datetime() normalises any stored
            # format so the comparison is reliable.
            cur.execute(
                "DELETE FROM stock "
                "WHERE datetime(COALESCE(added_date, '1970-01-01')) "
                "< datetime('now', ?)",
                (f"-{days} days",),
            )
            removed = cur.rowcount
        elif what == "stock_sold":
            cur.execute("DELETE FROM stock WHERE available=0")
            removed = cur.rowcount
        elif what == "stock_all":
            cur.execute("DELETE FROM stock")
            removed = cur.rowcount
        elif what == "panels_all":
            cur.execute("DELETE FROM panels")
            removed = cur.rowcount
        elif what == "src_all":
            cur.execute("DELETE FROM source_codes")
            removed = cur.rowcount
        db.commit()
        # Drop any cached country/stock lists so the deleted rows stop showing
        # immediately instead of lingering for the cache TTL.
        try:
            from plugins.buy import _LIVE_COUNTRY_CACHE
            _LIVE_COUNTRY_CACHE["ts"] = 0.0
            _LIVE_COUNTRY_CACHE["counts"] = {}
        except Exception:
            pass
        try:
            from plugins.product_panels import _cache as _pp_cache
            _pp_cache.clear()
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"cleanup execute failed ({what}): {exc}", exc_info=True)
        return await event.answer(f"❌ Delete failed: {exc}", alert=True)

    try:
        await event.answer(f"✅ Deleted {removed} row(s).")
    except Exception:
        pass
    await show_cleanup_menu(event)


def register_admin_cleanup(bot):
    @bot.on(events.CallbackQuery(pattern=r"^ac_menu$"))
    async def cb_ac_menu(e):
        await e.answer()
        await show_cleanup_menu(e)

    @bot.on(events.CallbackQuery(pattern=r"^ac_stock_old_menu$"))
    async def cb_ac_old_menu(e):
        await e.answer()
        await show_old_stock_menu(e)

    @bot.on(events.CallbackQuery(pattern=r"^ac_panels$"))
    async def cb_ac_panels(e):
        await e.answer()
        await show_panels(e)

    @bot.on(events.CallbackQuery(pattern=r"^ac_src$"))
    async def cb_ac_src(e):
        await e.answer()
        await show_sources(e)

    @bot.on(events.CallbackQuery(pattern=r"^ac_confirm\|([a-z_]+)(?:\|(\d+))?$"))
    async def cb_ac_confirm(e):
        what = e.pattern_match.group(1).decode()
        arg = e.pattern_match.group(2)
        arg = int(arg.decode()) if arg else None
        await e.answer()
        await _confirm(e, what, arg)

    @bot.on(events.CallbackQuery(pattern=r"^ac_do\|([a-z_]+)(?:\|(\d+))?$"))
    async def cb_ac_do(e):
        what = e.pattern_match.group(1).decode()
        arg = e.pattern_match.group(2)
        arg = int(arg.decode()) if arg else None
        await _execute(e, what, arg)

    @bot.on(events.CallbackQuery(pattern=r"^ac_panel_del\|(\d+)$"))
    async def cb_ac_panel_del(e):
        if not _can(e.sender_id):
            return await e.answer("⛔ Admin only.", alert=True)
        pid = int(e.pattern_match.group(1).decode())
        try:
            cur.execute("DELETE FROM panels WHERE id=?", (pid,))
            db.commit()
            await e.answer(f"✅ Panel #{pid} deleted.", alert=True)
        except Exception as exc:
            return await e.answer(f"❌ {exc}", alert=True)
        await show_panels(e)

    @bot.on(events.CallbackQuery(pattern=r"^ac_src_del\|(\d+)$"))
    async def cb_ac_src_del(e):
        if not _can(e.sender_id):
            return await e.answer("⛔ Admin only.", alert=True)
        sid = int(e.pattern_match.group(1).decode())
        try:
            cur.execute("DELETE FROM source_codes WHERE id=?", (sid,))
            db.commit()
            await e.answer(f"✅ Source code #{sid} deleted.", alert=True)
        except Exception as exc:
            return await e.answer(f"❌ {exc}", alert=True)
        await show_sources(e)
