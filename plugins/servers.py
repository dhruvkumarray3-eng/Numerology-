"""Servers screen.

Mirrors the reference app:
  Server-1 (OFF)
  Server-2 (Good Quality TG)
  Server-3 (TG NUM change)
  Server-4 (cheap phishing)
"""
import html
from telethon import events
from telethon.errors import MessageNotModifiedError

from config import (
    SERVERS_CONFIG,
    TEMPORASMS_API_KEY,
    PE_LOCATION,
    PE_CHECK,
    PE_LIGHTNING,
    PE_CROWN,
    logger,
)
from utils.keyboards import style_btn

SERVER_ICONS = {
    "bulk": "📦",
    "nonspam": "✅",
    "numchange": "🔁",
    "spam": "💰",
    "whatsapp": "💬",
    "allotp": "🧩",
}


def _server_status_key(idx):
    return f"server_status_{idx}"


def get_server_status(idx, default="on"):
    """Return the effective ON/OFF state for a server (1-based index).

    The owner can override the SERVERS_CONFIG default from the admin panel;
    the override is stored in the ``settings`` table so it survives restarts.
    """
    try:
        from database import cur
        row = cur.execute(
            "SELECT value FROM settings WHERE key=?", (_server_status_key(idx),)
        ).fetchone()
        if row and str(row[0]).strip().lower() in ("on", "off"):
            return str(row[0]).strip().lower()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"server status read failed for {idx}: {exc}")
    return default


def set_server_status(idx, status):
    """Persist an ON/OFF override for a server (1-based index)."""
    status = "on" if str(status).strip().lower() in ("on", "1", "true", "enable") else "off"
    try:
        from database import cur, db
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_server_status_key(idx), status),
        )
        db.commit()
        return status
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"server status write failed for {idx}: {exc}")
        return None


def parse_servers():
    servers = []
    for chunk in (SERVERS_CONFIG or "").split(","):
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) < 2:
            continue
        name = parts[0]
        status = parts[1].lower()
        mode = parts[2] if len(parts) > 2 else "bulk"
        servers.append({"name": name, "status": status, "mode": mode})
    # Apply owner overrides from the admin panel.
    for idx, srv in enumerate(servers, start=1):
        srv["status"] = get_server_status(idx, srv["status"])
    return servers


async def show_servers(event):
    servers = parse_servers()
    lines = []
    btns = []
    for idx, srv in enumerate(servers, start=1):
        icon = SERVER_ICONS.get(srv["mode"], "📦")
        if srv["status"] == "on":
            badge = "✅"
            lines.append(f"{icon} <b>{html.escape(srv['name'])}</b> — <b>ONLINE</b>")
            btns.append([style_btn(f"{icon} {srv['name']}", f"srv_open|{srv['mode']}", "success", icon=5409098988156629257)])
        else:
            badge = "🔴 OFF"
            lines.append(f"{icon} <b>{html.escape(srv['name'])}</b> — <b>{badge}</b>")
            btns.append([style_btn(f"{icon} {srv['name']} (OFF)", f"srv_off|{idx}", "danger")])

    msg = (
        f"<blockquote expandable>{PE_LOCATION} <b>🖥 Servers</b>\n\n"
        + "\n".join(lines)
        + f"\n\n<i>Pick a server to continue. Server-3 uses TemporaSMS for number change.</i></blockquote>"
    )
    btns.append([style_btn("🔙 Back", b"dashboard_main", "danger", icon=6129812419028982717)])

    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)


async def show_num_change(event):
    configured = bool(TEMPORASMS_API_KEY)
    status = "✅ Configured" if configured else "⚠️ Not configured (set TEMPORASMS_API_KEY)"
    msg = (
        f"<blockquote expandable>🔁 <b>TG Number Change (TemporaSMS)</b>\n\n"
        f"🔑 <b>API Status:</b> {status}\n\n"
        f"Send the <b>phone number</b> you want to migrate to, in international format "
        f"(e.g. <code>+919876543210</code>).\n\n"
        f"<i>We will request a temporary number from TemporaSMS and start the Telegram "
        f"login-code flow. Add TEMPORASMS_API_KEY in your host's variables to enable this.</i></blockquote>"
    )
    btns = [[style_btn("🔙 Back", b"servers_menu", "danger", icon=6129812419028982717)]]
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)


def register_servers(bot):
    @bot.on(events.CallbackQuery(pattern=r"^servers_menu$"))
    async def cb_servers_menu(e):
        await show_servers(e)

    @bot.on(events.CallbackQuery(pattern=r"^srv_open\|(\w+)$"))
    async def cb_srv_open(e):
        raw = e.pattern_match.group(1)
        mode = raw.decode() if isinstance(raw, bytes) else raw
        # Each server opens its own dedicated panel.
        from plugins.product_panels import PANELS, show_terms, show_countries as pp_countries
        if mode in PANELS:
            from plugins.product_panels import _terms_accepted
            if not _terms_accepted(e.sender_id, mode):
                return await show_terms(e, mode)
            return await pp_countries(e, mode, 1)
        if mode == "numchange":
            return await show_num_change(e)
        # Other servers open the buy catalogue filtered by that mode
        from plugins.buy import show_countries
        await show_countries(e, mode, 1)

    @bot.on(events.CallbackQuery(pattern=r"^srv_off\|(\d+)$"))
    async def cb_srv_off(e):
        await e.answer("🔴 This server is currently offline. Please pick another.", alert=True)
