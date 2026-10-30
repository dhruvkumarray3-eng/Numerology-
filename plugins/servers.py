"""Servers screen.

Four catalogues, exactly as the owner specified:

  Server-1  Basic TG Account      -> live Telegram account stock (bulk mode)
  Server-2  LZT Connected         -> LZT.market "Good Quality TG" accounts
  Server-3  TG Number Change      -> TemporaSMS, Telegram filter
  Server-4  Buy WhatsApp Account  -> TemporaSMS, WhatsApp filter

Server-3 and Server-4 are the same live panels used elsewhere in the bot, so
they stay ONLINE and show real TemporaSMS numbers whenever the provider has
stock.
"""
import html
from telethon import events
from telethon.errors import MessageNotModifiedError

from config import (
    SERVERS_CONFIG,
    PE_LOCATION,
    PE_CHECK,
    PE_LIGHTNING,
    PE_CROWN,
    logger,
)
from utils.keyboards import style_btn

SERVER_ICONS = {
    "bulk": "\U0001F4E6",
    "nonspam": "\U0001F6D2",
    "numchange": "\U0001F501",
    "spam": "\U0001F4B0",
    "whatsapp": "\U0001F4AC",
    "allotp": "\U0001F9E9",
}

# One-line explanation under each server name on the Servers screen.
SERVER_BLURBS = {
    "bulk": "Live Telegram accounts, standard stock.",
    "nonspam": "LZT.market connected \u2014 Good Quality TG accounts.",
    "numchange": "TemporaSMS Telegram filter \u2014 live numbers for TG number change.",
    "spam": "Cheap Telegram accounts from live stock.",
    "whatsapp": "TemporaSMS WhatsApp filter \u2014 live numbers for WhatsApp accounts.",
    "allotp": "Every app on the OTP panel.",
}


def _lzt_ready():
    """True when an LZT API key is configured (Server-2 is 'connected')."""
    try:
        from database import get_lzt_key
        return bool(get_lzt_key())
    except Exception:  # pragma: no cover - defensive
        return False


def _otp_ready():
    """True when the TemporaSMS key is configured (Server-3/4 are live)."""
    try:
        from utils import temporasms
        return bool(temporasms.configured())
    except Exception:  # pragma: no cover - defensive
        return False


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
    """Render the four servers with their live connection status.

    Server-2 shows whether LZT is connected, Server-3/4 show whether the
    TemporaSMS key is live, so the owner can see at a glance that the
    number-change and WhatsApp catalogues are actually online.
    """
    servers = parse_servers()
    lines = []
    btns = []
    lzt_ok = _lzt_ready()
    otp_ok = _otp_ready()

    for idx, srv in enumerate(servers, start=1):
        mode = srv["mode"]
        icon = SERVER_ICONS.get(mode, "\U0001F4E6")
        blurb = SERVER_BLURBS.get(mode, "")
        if srv["status"] == "on":
            lines.append(f"{icon} <b>{html.escape(srv['name'])}</b> \u2014 <b>ONLINE</b>")
            if blurb:
                lines.append(f"   <i>{html.escape(blurb)}</i>")
            btns.append([style_btn(f"{icon} {srv['name']}",
                                   f"srv_open|{mode}", "success",
                                   icon=5409098988156629257)])
        else:
            lines.append(f"{icon} <b>{html.escape(srv['name'])}</b> \u2014 <b>\U0001F534 OFF</b>")
            if blurb:
                lines.append(f"   <i>{html.escape(blurb)}</i>")
            btns.append([style_btn(f"{icon} {srv['name']} (OFF)",
                                   f"srv_off|{idx}", "danger", icon="warning")])

    lzt_badge = (PE_CHECK + " Connected") if lzt_ok else ("\u26A0\uFE0F Key missing")
    otp_badge = (PE_CHECK + " Live") if otp_ok else ("\u26A0\uFE0F Key missing")
    status_lines = [
        f"\U0001F6D2 <b>LZT.market:</b> {lzt_badge}",
        f"\U0001F4F1 <b>TemporaSMS:</b> {otp_badge}",
    ]

    msg = (
        f"<blockquote expandable>{PE_LOCATION} <b>\U0001F5A5 Servers</b>\n\n"
        + "\n".join(lines)
        + "\n\n" + "\n".join(status_lines)
        + "\n\n<i>Server-3 and Server-4 use the live TemporaSMS panel "
          "(Telegram / WhatsApp filters).</i></blockquote>"
    )
    btns.append([style_btn("\U0001F504 Refresh", b"servers_menu", "primary",
                           icon=5409320020058584473)])
    btns.append([style_btn("\U0001F519 Back", b"dashboard_main", "danger",
                           icon=6129812419028982717)])

    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
        except Exception as exc:  # noqa: BLE001 - never leave a dead button
            logger.warning(f"servers edit failed: {exc}")
            try:
                await event.respond(msg, buttons=btns)
            except Exception:
                pass
    else:
        await event.respond(msg, buttons=btns)


async def show_num_change(event):
    from utils import temporasms
    configured = temporasms.configured()
    status = "✅ Configured" if configured else "⚠️ Not configured (Admin → OTP / SMS Key)"
    msg = (
        f"<blockquote expandable>🔁 <b>TG Number Change (TemporaSMS)</b>\n\n"
        f"🔑 <b>API Status:</b> {status}\n\n"
        f"Send the <b>phone number</b> you want to migrate to, in international format "
        f"(e.g. <code>+919876543210</code>).\n\n"
        f"<i>We will request a temporary number from TemporaSMS and start the Telegram "
        f"login-code flow. Add it in Admin → 🔐 OTP / SMS Key, or set TEMPORASMS_API_KEY in your host variables.</i></blockquote>"
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
        # Server-2 is the LZT catalogue; accept the friendly alias too.
        if mode == "lzt":
            mode = "nonspam"

        from plugins.product_panels import (
            PANELS, show_terms, show_countries as pp_countries, _terms_accepted,
        )
        # Server-3 (numchange) and Server-4 (whatsapp) are live TemporaSMS
        # panels, so they get the terms gate + country list like the rest of
        # the bot.
        if mode in PANELS:
            if not _terms_accepted(e.sender_id, mode):
                return await show_terms(e, mode)
            return await pp_countries(e, mode, 1)
        if mode == "numchange":
            return await show_num_change(e)
        # Server-1 (bulk) and Server-2 (nonspam/LZT) open the account catalogue.
        from plugins.buy import show_countries
        await show_countries(e, mode, 1)

    @bot.on(events.CallbackQuery(pattern=r"^srv_off\|(\d+)$"))
    async def cb_srv_off(e):
        await e.answer("\U0001F534 This server is currently offline. Please pick another.", alert=True)
