"""Free Temp Mail section (MTempMail API).

Users get a disposable inbox, can create fresh addresses, refresh, and read
incoming verification mails / OTPs right inside the bot. Each inbox lives for
50 minutes, with a live countdown, Copy Email / Refresh Inbox / Cancel Mail
controls.
"""
from __future__ import annotations

import html
import re
import time
from typing import Dict, List

from telethon import events
from telethon.errors import MessageNotModifiedError

from config import logger, PE_CHECK, PE_LIGHTNING, PE_GIFT
from database import cur, db
from utils.keyboards import style_btn
from utils.livecount import register_live, unregister_live
from utils import tempmail as tm

# uid -> {"email": str, "domain": str, "expires": int}
_tm_state: Dict[int, Dict[str, object]] = {}

MAIL_TTL = 50 * 60  # 50 minutes, matching the reference UI


def _ensure_table() -> None:
    try:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS tempmail_inboxes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id INTEGER NOT NULL,
                   email TEXT NOT NULL,
                   domain TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   expires_at INTEGER,
                   UNIQUE(user_id, email)
               )"""
        )
        # Older installs may not have expires_at yet.
        cols = [r[1] for r in cur.execute("PRAGMA table_info(tempmail_inboxes)").fetchall()]
        if "expires_at" not in cols:
            cur.execute("ALTER TABLE tempmail_inboxes ADD COLUMN expires_at INTEGER")
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.debug(f"tempmail table init failed: {exc}")


def _save_inbox(uid: int, email: str, domain: str = "", expires: int | None = None) -> None:
    try:
        expires = int(expires or (time.time() + MAIL_TTL))
        cur.execute(
            "INSERT OR IGNORE INTO tempmail_inboxes (user_id, email, domain, expires_at) VALUES (?,?,?,?)",
            (uid, email, domain, expires),
        )
        cur.execute(
            "UPDATE tempmail_inboxes SET expires_at=? WHERE user_id=? AND email=?",
            (expires, uid, email),
        )
        db.commit()
    except Exception as exc:
        logger.debug(f"tempmail save failed: {exc}")


def _expires_for(uid: int, email: str) -> int:
    try:
        row = cur.execute(
            "SELECT expires_at FROM tempmail_inboxes WHERE user_id=? AND email=?",
            (uid, email),
        ).fetchone()
        if row and row[0]:
            return int(row[0])
    except Exception:
        pass
    return int(time.time() + MAIL_TTL)


def _user_inboxes(uid: int) -> List[str]:
    try:
        rows = cur.execute(
            "SELECT email FROM tempmail_inboxes WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (uid,),
        ).fetchall()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        return []


def _delete_inbox(uid: int, email: str) -> None:
    try:
        cur.execute("DELETE FROM tempmail_inboxes WHERE user_id=? AND email=?", (uid, email))
        db.commit()
    except Exception:
        pass
    _tm_state.pop(uid, None)


def _countdown(expires: int) -> tuple[str, bool]:
    left = int(expires - time.time())
    if left <= 0:
        return "00:00", True
    return f"{left // 60:02d}:{left % 60:02d}", False


def _short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _edit_or_send(event, msg: str, buttons):
    """Send or edit the message and return the resulting Message object."""
    if isinstance(event, events.CallbackQuery.Event):
        try:
            return await event.edit(msg, buttons=buttons)
        except MessageNotModifiedError:
            try:
                return await event.get_message()
            except Exception:
                return None
    return await event.respond(msg, buttons=buttons)


def _home_text() -> str:
    return (
        f"<blockquote expandable>{PE_GIFT} <b>FREE TEMP MAIL</b>\n\n"
        "Generate a temporary disposable email and receive incoming messages "
        "directly here.\n\n"
        "📬 <b>Instant mailbox</b>\n"
        "✈️ <b>Receive emails in Telegram</b>\n"
        "⏳ <b>50-minute mailbox</b>\n\n"
        "<i>No signup, no password — your address is ready in one tap.</i></blockquote>"
    )


async def show_home(event):
    btns = [
        [style_btn("📧 Get Temp Mail", b"tm_new", "success", icon=5796209712009581332)],
    ]
    uid = event.sender_id
    inboxes = _user_inboxes(uid)
    if inboxes:
        btns.append([style_btn("🗂 My Inboxes", b"tm_list", "primary", icon=5409098988156629257)])
    btns.append([style_btn("🔙 Back", b"dashboard_main", "danger", icon=6129812419028982717)])
    await _edit_or_send(event, _home_text(), btns)


def _inbox_text(email: str, expires: int, messages: List[dict]) -> str:
    left, expired = _countdown(expires)
    head = (
        f"<blockquote expandable>📧 <b>YOUR TEMP MAIL</b>\n\n"
        f"📮 <b>Email:</b>\n<code>{html.escape(email)}</code>\n\n"
        f"⏳ <b>Time Remaining:</b> <b>{left}</b>\n\n"
    )
    if expired:
        head += "🔴 <b>This mailbox has expired.</b> Generate a new one.\n"
    elif messages:
        head += f"🟢 <b>{len(messages)} message(s)</b> received.\n"
    else:
        head += "🟡 <b>Waiting for incoming mail.</b>\n"
        head += "QuickCodes is monitoring your temporary inbox for new messages.\n"

    head += (
        "\n⚠️ <b>IMPORTANT:</b>\n"
        "• This mailbox is temporary.\n"
        "• You can receive emails while it is active.\n"
        "• The mailbox automatically expires.\n"
        "• After expiration you can generate a new mailbox.\n"
    )
    if messages:
        head += "\n──────────────\n"
        for m in messages[:6]:
            otp = tm.extract_otp(m.get("body") or "")
            badge = f" 🔑 <code>{otp}</code>" if otp else ""
            head += (
                f"• <b>{html.escape(_short(m.get('subject') or '(no subject)', 45))}</b> "
                f"<i>from {html.escape(_short(m.get('from') or '?', 22))}</i>{badge}\n"
            )
    head += "</blockquote>"
    return head


def _inbox_buttons(email: str, messages: List[dict]) -> list:
    btns = []
    for m in messages[:5]:
        mid = m.get("id")
        label = _short(m.get("subject") or "(no subject)", 30)
        btns.append([style_btn(f"📩 {label}", f"tm_msg|{email}|{mid}", "primary", icon=5373130604147654226)])
    btns.append([
        style_btn("📋 Copy Email", f"tm_copy|{email}", "success", icon=5409098988156629257),
        style_btn("🔄 Refresh Inbox", f"tm_inbox|{email}", "success", icon=5409320020058584473),
    ])
    btns.append([
        style_btn("❌ Cancel Mail", f"tm_cancel|{email}", "danger", icon=6129888444245089008),
        style_btn("➕ New Mail", b"tm_new", "primary", icon=5796209712009581332),
    ])
    btns.append([style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)])
    return btns


# ---------------------------------------------------------------------------
# Live countdown + auto inbox refresh
# ---------------------------------------------------------------------------
def _start_live_inbox(event, sent_msg, email: str, expires: int, messages: List[dict]) -> None:
    """Keep the inbox card ticking every 5s and auto-poll for new mail.

    The countdown is recomputed from `expires` on every tick, so it always shows
    the true remaining time even if the bot restarts or the worker lags.
    """
    try:
        chat_id = event.chat_id
        msg_id = sent_msg.id
    except Exception:
        return

    cache = {"messages": list(messages or []), "poll_at": time.time() + 12.0}
    key = f"tm:{email}"

    async def _render():
        now = time.time()
        # Re-fetch the mailbox roughly every 12 seconds so new OTPs appear by
        # themselves, without hammering the Temp Mail API.
        if now >= cache["poll_at"]:
            cache["poll_at"] = now + 12.0
            try:
                fresh = await tm.get_messages(email)
                if fresh is not None:
                    cache["messages"] = fresh
            except Exception:
                pass
        left, expired = _countdown(expires)
        text = _inbox_text(email, expires, cache["messages"])
        return text, _inbox_buttons(email, cache["messages"]), expired

    register_live(key, event.client, chat_id, msg_id, _render, interval=5.0)

async def create_inbox(event):
    uid = event.sender_id
    try:
        if isinstance(event, events.CallbackQuery.Event):
            await event.answer("Creating your temp email…")
    except Exception:
        pass
    try:
        data = await tm.create_email()
    except tm.TempMailError as exc:
        await _edit_or_send(
            event,
            f"<blockquote>❌ <b>Could not create a temp email</b>\n\n{html.escape(str(exc))}</blockquote>",
            [[style_btn("🔁 Try Again", b"tm_new", "success", icon=5796209712009581332)],
             [style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)]],
        )
        return
    except Exception as exc:
        logger.exception(f"tempmail create failed: {exc}")
        await _edit_or_send(
            event,
            "<blockquote>❌ <b>Temp Mail is temporarily unavailable.</b>\nPlease try again in a moment.</blockquote>",
            [[style_btn("🔁 Try Again", b"tm_new", "success", icon=5796209712009581332)],
             [style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)]],
        )
        return

    email = str(data.get("email") or "").strip()
    domain = str(data.get("domain") or "").strip()
    if not email:
        await show_home(event)
        return
    expires = int(time.time() + MAIL_TTL)
    _tm_state[uid] = {"email": email, "domain": domain, "expires": expires}
    _save_inbox(uid, email, domain, expires)
    sent = await _edit_or_send(event, _inbox_text(email, expires, []), _inbox_buttons(email, []))
    if sent is not None:
        _start_live_inbox(event, sent, email, expires, [])


async def show_list(event):
    uid = event.sender_id
    inboxes = _user_inboxes(uid)
    if not inboxes:
        await show_home(event)
        return
    lines = [f"<blockquote expandable>{PE_LIGHTNING} <b>🗂 Your Temp Inboxes</b>\n"]
    for i, email in enumerate(inboxes, 1):
        exp = _expires_for(uid, email)
        left, expired = _countdown(exp)
        state = "🔴 expired" if expired else f"⏳ {left}"
        lines.append(f"{i}. <code>{html.escape(email)}</code> — {state}")
    lines.append("</blockquote>")
    btns = [
        [style_btn(f"📥 {email}", f"tm_inbox|{email}", "primary", icon=5373130604147654226)]
        for email in inboxes[:6]
    ]
    btns.append([style_btn("➕ Get Temp Mail", b"tm_new", "success", icon=5796209712009581332)])
    btns.append([style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)])
    await _edit_or_send(event, "\n".join(lines), btns)


async def show_inbox(event, email: str):
    uid = event.sender_id
    if not email:
        await show_home(event)
        return
    _tm_state.setdefault(uid, {})["email"] = email
    expires = _expires_for(uid, email)
    try:
        messages = await tm.get_messages(email)
    except tm.TempMailError as exc:
        await _edit_or_send(
            event,
            f"<blockquote>❌ <b>Could not load inbox</b>\n\n{html.escape(str(exc))}</blockquote>",
            [[style_btn("🔄 Refresh Inbox", f"tm_inbox|{email}", "success", icon=5409320020058584473)],
             [style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)]],
        )
        return
    except Exception as exc:
        logger.exception(f"tempmail inbox failed: {exc}")
        messages = []

    sent = await _edit_or_send(event, _inbox_text(email, expires, messages), _inbox_buttons(email, messages))
    if sent is not None:
        _start_live_inbox(event, sent, email, expires, messages)


async def copy_email(event, email: str):
    """Deliver the address as a standalone <code> block.

    Telegram copies a <code> block to the clipboard the moment it is tapped,
    which is the only one-tap copy that works on every client (inline buttons
    have no copy action in this MTProto library version).
    """
    try:
        await event.answer("📋 Tap the code below to copy — done!", alert=False)
    except Exception:
        pass
    try:
        await event.respond(
            f"<blockquote>📋 <b>𝐓𝐚𝐩 𝐭𝐨 𝐂𝐨𝐩𝐲</b>\n\n"
            f"<code>{html.escape(email)}</code>\n\n"
            f"<i>✨ One tap on the address copies it to your clipboard.</i></blockquote>"
        )
    except Exception as exc:
        logger.debug(f"tempmail copy failed: {exc}")


async def cancel_mail(event, email: str):
    uid = event.sender_id
    _delete_inbox(uid, email)
    try:
        await event.answer("❌ Mailbox cancelled.", alert=False)
    except Exception:
        pass
    await show_home(event)


async def show_message(event, email: str, message_id: str):
    try:
        msg = await tm.get_message(email, message_id)
    except Exception as exc:
        logger.exception(f"tempmail message failed: {exc}")
        msg = {"body": "", "subject": "", "from": ""}

    body_text = tm._strip_html(msg.get("body") or "")
    otp = tm.extract_otp(body_text)
    shown = _short(body_text, 2800) if body_text else "No readable content in this message."
    parts = [
        f"<blockquote expandable>📩 <b>{html.escape(msg.get('subject') or '(no subject)')}</b>\n",
        f"👤 <b>From:</b> {html.escape(msg.get('from') or 'Unknown')}\n",
    ]
    if msg.get("date"):
        parts.append(f"🕒 <b>Date:</b> {html.escape(str(msg.get('date')))}\n")
    if otp:
        parts.append(f"\n🔑 <b>Detected code:</b> <code>{otp}</code>\n")
    parts.append(f"\n──────────────\n{html.escape(shown)}</blockquote>")
    btns = [
        [style_btn("🔄 Back to Inbox", f"tm_inbox|{email}", "success", icon=5409320020058584473)],
        [style_btn("🔙 Home", b"tm_home", "danger", icon=6129812419028982717)],
    ]
    await _edit_or_send(event, "".join(parts), btns)


def register_tempmail(bot):
    _ensure_table()

    @bot.on(events.NewMessage(pattern=r"^/(?:tempmail|tm)(?:@\w+)?$"))
    async def cmd_tempmail(e):
        await show_home(e)

    @bot.on(events.CallbackQuery(pattern=r"^tm_home$"))
    async def cb_tm_home(e):
        await show_home(e)

    @bot.on(events.CallbackQuery(pattern=r"^tm_new$"))
    async def cb_tm_new(e):
        await create_inbox(e)

    @bot.on(events.CallbackQuery(pattern=r"^tm_list$"))
    async def cb_tm_list(e):
        await show_list(e)

    @bot.on(events.CallbackQuery(pattern=r"^tm_inbox\|"))
    async def cb_tm_inbox(e):
        email = e.data.decode(errors="ignore").split("|", 1)[1]
        await show_inbox(e, email)

    @bot.on(events.CallbackQuery(pattern=r"^tm_copy\|"))
    async def cb_tm_copy(e):
        email = e.data.decode(errors="ignore").split("|", 1)[1]
        await copy_email(e, email)

    @bot.on(events.CallbackQuery(pattern=r"^tm_cancel\|"))
    async def cb_tm_cancel(e):
        email = e.data.decode(errors="ignore").split("|", 1)[1]
        await cancel_mail(e, email)

    @bot.on(events.CallbackQuery(pattern=r"^tm_msg\|"))
    async def cb_tm_msg(e):
        parts = e.data.decode(errors="ignore").split("|")
        if len(parts) < 3:
            await show_home(e)
            return
        await show_message(e, parts[1], parts[2])
