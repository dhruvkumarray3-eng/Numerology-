"""Live admin audit logging for bot interactions.

Message bodies, callback payload parameters, OTPs, credentials, and payment
proof contents are intentionally never included in generic activity logs.
"""
import asyncio
from datetime import datetime, timezone
import html
import re

from telethon import events

from config import logger

_ALLOWED_DETAILS = {
    "target_user_id", "order_id", "deposit_id", "amount", "currency",
    "method", "product", "status", "command", "callback", "message_type",
    "length", "reason", "user_name", "username",
}
_TASKS = set()


def _safe_action(action):
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", str(action or "unknown"))[:64]


def _safe_detail(key, value):
    if key == "command":
        raw = str(value or "").strip().split(maxsplit=1)[0] if value else ""
        raw = raw.split("@", 1)[0]
        return re.sub(r"[^A-Za-z0-9_/-]", "", raw)[:48] or "unknown"
    if key == "callback":
        raw = str(value or "").split("|", 1)[0]
        return re.sub(r"[^A-Za-z0-9_.:-]", "", raw)[:48] or "unknown"
    if key in {"target_user_id", "deposit_id", "length"}:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return "unknown"
    if key == "amount":
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return "unknown"
    return html.escape(str(value or "—")[:100])


async def _actor_details(client, actor_id):
    """Resolve display identity without reading message text or callback payloads."""
    details = {"user_name": "unknown", "username": "unknown"}
    try:
        entity = await client.get_entity(int(actor_id))
        first = str(getattr(entity, "first_name", "") or "").strip()
        last = str(getattr(entity, "last_name", "") or "").strip()
        name = " ".join(part for part in (first, last) if part).strip()
        username = str(getattr(entity, "username", "") or "").strip()
        details["user_name"] = name[:100] if name else "unknown"
        details["username"] = f"@{username[:99]}" if username else "unknown"
    except Exception:
        # Fallback/test clients may not implement entity lookup; auditing must
        # never delay or break the user's interaction in that case.
        pass
    return details


async def log_admin_action(client, *, actor_id, action, details=None):
    """Send one safe audit event to the personal channel or legacy fallback."""
    try:
        from config import ADMIN_LOG_CHANNEL_ID
        if ADMIN_LOG_CHANNEL_ID:
            # Private activity metadata belongs only in the owner's private
            # channel; purchase/deposit records continue using all operational
            # channels through get_log_channels_db().
            channels = [ADMIN_LOG_CHANNEL_ID]
        else:
            from database import get_log_channels_db
            channels = get_log_channels_db()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not load audit-log channels: %s", exc)
        return 0

    if not channels:
        logger.warning("Audit event not delivered: no log channel configured (%s)", action)
        return 0
    if client is None:
        logger.error("Audit event not delivered: Telegram client unavailable (%s)", action)
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        actor = str(int(actor_id))
    except (TypeError, ValueError):
        actor = "unknown"
    identity = await _actor_details(client, actor)
    lines = [
        "<blockquote><b>BOT ACTIVITY</b>",
        f"<b>Time:</b> <code>{stamp}</code>",
        f"<b>Name:</b> <code>{_safe_detail('user_name', identity['user_name'])}</code>",
        f"<b>Username:</b> <code>{_safe_detail('username', identity['username'])}</code>",
        f"<b>User ID:</b> <code>{actor}</code>",
        f"<b>Action:</b> <code>{html.escape(_safe_action(action))}</code>",
    ]
    for key, value in (details or {}).items():
        if key not in _ALLOWED_DETAILS:
            continue
        label = key.replace("_", " ").title()
        lines.append(f"<b>{html.escape(label)}:</b> <code>{_safe_detail(key, value)}</code>")
    lines.append("<i>Message content and sensitive payloads are not recorded.</i></blockquote>")
    message = "\n".join(lines)

    delivered = 0
    for channel in channels:
        try:
            await client.send_message(channel, message, parse_mode="html")
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Audit log send failed for channel %s: %s", channel, exc)
    if not delivered:
        logger.error("Audit event failed for every configured channel (%s)", action)
    return delivered


def _task_done(task):
    _TASKS.discard(task)
    try:
        task.result()
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected audit logger task failure: %s", exc, exc_info=True)


def schedule_admin_log(client, *, actor_id, action, details=None):
    """Queue a channel log without delaying the bot's interactive handler."""
    try:
        task = asyncio.get_running_loop().create_task(
            log_admin_action(client, actor_id=actor_id, action=action, details=details)
        )
    except RuntimeError:
        logger.warning("No running event loop; audit event skipped (%s)", action)
        return None
    _TASKS.add(task)
    task.add_done_callback(_task_done)
    return task


def register_audit_handlers(bot):
    """Track private bot interactions, excluding message bodies and payloads."""
    from config import ADMIN_LOG_CHANNEL_ID
    if ADMIN_LOG_CHANNEL_ID:
        logger.info("Private admin audit channel configured: %s", ADMIN_LOG_CHANNEL_ID)
    else:
        logger.warning(
            "ADMIN_LOG_CHANNEL_ID is unset; private action logs will use legacy log channels."
        )

    @bot.on(events.NewMessage(incoming=True))
    async def audit_incoming_message(event):
        try:
            if not getattr(event, "is_private", False) or not event.sender_id:
                return
            text = str(getattr(event, "raw_text", "") or "").strip()
            if text.startswith("/"):
                command = text.split(maxsplit=1)[0]
                schedule_admin_log(
                    bot, actor_id=event.sender_id, action="command",
                    details={"command": command},
                )
                return
            kind = "text" if text else ("media" if getattr(event, "media", None) else "service")
            details = {"message_type": kind}
            if text:
                details["length"] = len(text)
            schedule_admin_log(
                bot, actor_id=event.sender_id, action="message", details=details
            )
        except Exception as exc:  # noqa: BLE001 - auditing must never break UX
            logger.error("Incoming-message audit failed: %s", exc)

    @bot.on(events.CallbackQuery)
    async def audit_button_action(event):
        try:
            if not getattr(event, "is_private", False) or not event.sender_id:
                return
            raw = getattr(event, "data", b"")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            callback = str(raw or "").split("|", 1)[0]
            schedule_admin_log(
                bot, actor_id=event.sender_id, action="button_click",
                details={"callback": callback},
            )
        except Exception as exc:  # noqa: BLE001 - auditing must never break UX
            logger.error("Callback audit failed: %s", exc)

    return True
