"""Free Temp Mail section (MTempMail API).

Users get a disposable inbox, can create fresh addresses, refresh, and read
incoming verification mails / OTPs right inside the bot.
"""
from __future__ import annotations

import html
import re
from typing import Dict, List

from telethon import events
from telethon.errors import MessageNotModifiedError

from config import logger, PE_CHECK, PE_LIGHTNING, PE_GIFT
from database import cur, db
from utils.keyboards import style_btn
from utils import tempmail as tm

# uid -> {"email": str, "domain": str, "created": str}
_tm_state: Dict[int, Dict[str, str]] = {}


def _ensure_table() -> None:
    try:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS tempmail_inboxes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id INTEGER NOT NULL,
                   email TEXT NOT NULL,
                   domain TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(user_id, email)
               )"""
        )
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.debug(f"tempmail table init failed: {exc}")


def _save_inbox(uid: int, email: str, domain: str = "") -> None:
    try:
        cur.execute(
            "INSERT OR IGNORE INTO tempmail_inboxes (user_id, email, domain) VALUES (?,?,?)",
            (uid, email, domain),
        )
        db.commit()
    except Exception as exc:
        logger.debug(f"tempmail save failed: {exc}")


def _user_inboxes(uid: int) -> List[str]:
    try:
        rows = cur.execute(
            "SELECT email FROM tempmail_inboxes WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (uid,),
        ).fetchall()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        return []


def _short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _edit_or_send(event, msg: str, buttons):
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=buttons)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=buttons)


async def show_home(event):
    uid = event.sender_id
    inboxes = _user_inboxes(uid)
    current = _tm_state.get(uid, {}).get("email") or (inboxes[0] if inboxes else "")
    body = (
        f"<blockquote expandable>{PE_GIFT} <b>📧 Free Temp Mail</b>\n\n"
        "Create a disposable email address instantly — perfect for receiving "
        "verification codes, OTPs and confirmation links without exposing your "
        "real inbox.\n\n"
        f"🟢 <b>Free</b> · ⚡ <b>Instant</b> · 🔒 <b>Private</b>\n"
        "Messages usually arrive within a few seconds — tap <b>Refresh</b> to check."
    )
    if current:
        body += f"\n\n📬 <b>Current inbox:</b> <code>{html.escape(current)}</code>"
    body += "</blockquote>"

    btns = [
        [style_btn("➕ Create New Email", b"tm_new", "success", icon=5796209712009581332)],
    ]
    if current:
        btns.append([style_btn("📥 Check Inbox", f"tm_inbox|{current}", "primary", icon=5373130604147654226)])
        btns.append([style_btn("🔄 Refresh", f"tm_inbox|{current}", "success", icon=5409320020058584473)])
    if inboxes:
        btns.append([style_btn("🗂 My Inboxes", b"tm_list", "primary", icon=5409098988156629257)])
    btns.append([style_btn("🔙 Back", b"dashboard_main", "danger", icon=6129812419028982717)])
    await _edit_or_send(event, body, btns)


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
    expire = str(data.get("expire_at") or "").strip()
    _tm_state[uid] = {"email": email, "domain": domain, "created": str(data.get("created_at") or "")}
    _save_inbox(uid, email, domain)

    body = (
        f"<blockquote expandable>{PE_CHECK} <b>Your temp email is ready!</b>\n\n"
        f"📧 <b>Address:</b>\n<code>{html.escape(email)}</code>\n\n"
        f"🌐 <b>Domain:</b> {html.escape(domain or 'auto')}\n"
        f"⏳ <b>Expires:</b> {html.escape(expire or 'in ~10 minutes')}\n\n"
        "Use this address on the site you are signing up for. When the mail "
        "arrives, tap <b>Check Inbox</b> below.</blockquote>"
    )
    btns = [
        [style_btn("📥 Check Inbox", f"tm_inbox|{email}", "success", icon=5373130604147654226)],
        [style_btn("➕ New Email", b"tm_new", "primary", icon=5796209712009581332),
         style_btn("🗂 My Inboxes", b"tm_list", "primary", icon=5409098988156629257)],
        [style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)],
    ]
    await _edit_or_send(event, body, btns)


async def show_list(event):
    uid = event.sender_id
    inboxes = _user_inboxes(uid)
    if not inboxes:
        await show_home(event)
        return
    lines = [f"<blockquote expandable>{PE_LIGHTNING} <b>🗂 Your Temp Inboxes</b>\n"]
    for i, email in enumerate(inboxes, 1):
        lines.append(f"{i}. <code>{html.escape(email)}</code>")
    lines.append("</blockquote>")
    btns = [
        [style_btn(f"📥 {email}", f"tm_inbox|{email}", "primary", icon=5373130604147654226)]
        for email in inboxes[:6]
    ]
    btns.append([style_btn("➕ Create New Email", b"tm_new", "success", icon=5796209712009581332)])
    btns.append([style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)])
    await _edit_or_send(event, "\n".join(lines), btns)


async def show_inbox(event, email: str):
    uid = event.sender_id
    if not email:
        await show_home(event)
        return
    _tm_state.setdefault(uid, {})["email"] = email
    _save_inbox(uid, email)
    try:
        messages = await tm.get_messages(email)
    except tm.TempMailError as exc:
        await _edit_or_send(
            event,
            f"<blockquote>❌ <b>Could not load inbox</b>\n\n{html.escape(str(exc))}</blockquote>",
            [[style_btn("🔄 Refresh", f"tm_inbox|{email}", "success", icon=5409320020058584473)],
             [style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)]],
        )
        return
    except Exception as exc:
        logger.exception(f"tempmail inbox failed: {exc}")
        messages = []

    if not messages:
        body = (
            f"<blockquote expandable>📭 <b>Inbox is empty</b>\n\n"
            f"📧 <code>{html.escape(email)}</code>\n\n"
            "No messages yet. Mails can take a few seconds to arrive — "
            "tap <b>Refresh</b> after the site sends the code.</blockquote>"
        )
        btns = [
            [style_btn("🔄 Refresh", f"tm_inbox|{email}", "success", icon=5409320020058584473)],
            [style_btn("➕ New Email", b"tm_new", "primary", icon=5796209712009581332)],
            [style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)],
        ]
        await _edit_or_send(event, body, btns)
        return

    lines = [
        f"<blockquote expandable>📥 <b>Inbox</b> · <code>{html.escape(email)}</code>\n",
        f"🟢 <b>{len(messages)}</b> message(s)\n",
    ]
    for m in messages[:8]:
        otp = tm.extract_otp(m.get("body") or "")
        badge = f" 🔑 <code>{otp}</code>" if otp else ""
        lines.append(f"• <b>{html.escape(_short(m.get('subject') or '(no subject)', 45))}</b> "
                     f"<i>from {html.escape(_short(m.get('from') or '?', 25))}</i>{badge}")
    lines.append("</blockquote>")
    btns = []
    for m in messages[:6]:
        mid = m.get("id")
        label = _short(m.get("subject") or "(no subject)", 32)
        btns.append([style_btn(f"📩 {label}", f"tm_msg|{email}|{mid}", "primary", icon=5373130604147654226)])
    btns.append([style_btn("🔄 Refresh", f"tm_inbox|{email}", "success", icon=5409320020058584473),
                 style_btn("➕ New Email", b"tm_new", "primary", icon=5796209712009581332)])
    btns.append([style_btn("🔙 Back", b"tm_home", "danger", icon=6129812419028982717)])
    await _edit_or_send(event, "\n".join(lines), btns)


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

    @bot.on(events.CallbackQuery(pattern=r"^tm_msg\|"))
    async def cb_tm_msg(e):
        parts = e.data.decode(errors="ignore").split("|")
        if len(parts) < 3:
            await show_home(e)
            return
        await show_message(e, parts[1], parts[2])
