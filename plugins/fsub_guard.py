"""Force-subscribe guard: verify channel membership on EVERY interaction.

Before this module the join check only ran inside ``/start`` and the
``verify_join`` button.  A user could join once, tap ``/start``, then leave the
channel and keep using every button for ever.  The owner wants the bot to
verify *by itself* every time:

    "jo banda channel leave krega bot har baar verify karega ... agar leave
     krdiya hoga toh phirse join krne ko bolega, or channel me rhega toh
     buttons sab kaam karenge"

Design notes
------------
* Registered **first** in ``main.py`` so nothing can run before it.
* Only private, incoming updates are inspected (never channel posts, never
  the bot's own messages).
* ``/start`` and the ``verify_join`` button are skipped on purpose: they are
  the screens that *perform* the join flow, so gating them would deadlock.
* Admins and the "FSub OFF" / "no channels configured" cases pass instantly
  (``check_channel_joined`` already handles the admin bypass).
* A short success cache keeps a busy user from hammering Telegram with a
  ``GetParticipantRequest`` per keystroke.  Failures are never cached, so the
  moment a user leaves, the very next tap is blocked.
"""
import time

from telethon import Button, events
from telethon.tl import types

from config import logger
from utils.helpers import check_channel_joined, get_unjoined_channels

# How long a *successful* membership check is trusted.  Small on purpose: the
# owner wants the bot to re-verify constantly, but a per-message Telegram API
# round trip would hit flood limits during a normal conversation.
JOIN_CACHE_TTL = 20.0

# uid -> monotonic timestamp of the last successful verification
_joined_ok = {}

# Updates that must never be blocked, because they drive the join flow itself.
SKIP_TEXTS = ("/start",)
SKIP_CALLBACKS = (b"verify_join",)


def _trusted(uid):
    ts = _joined_ok.get(uid)
    if ts is None:
        return False
    if (time.monotonic() - ts) < JOIN_CACHE_TTL:
        return True
    _joined_ok.pop(uid, None)
    return False


def _remember(uid):
    _joined_ok[uid] = time.monotonic()


def forget(uid):
    """Drop the cached result for *uid* (call after a join/leave event)."""
    _joined_ok.pop(uid, None)


def _is_admin_safe(uid):
    """Admin lookup that can never raise (a broken DB must not lock users out)."""
    try:
        from database import is_admin
        return bool(is_admin(uid))
    except Exception:
        return False


async def _needs_join(bot, uid):
    """True when *uid* must (re)join before using the bot."""
    if _trusted(uid):
        return False
    try:
        joined = await check_channel_joined(bot, uid, _is_admin_safe)
    except Exception as exc:  # noqa: BLE001 - never lock a user out on an error
        logger.warning("FSub check failed for %s (%s) - allowing", uid, exc)
        return False
    if joined:
        _remember(uid)
        return False
    return True


async def _join_screen(bot, event, uid):
    """Render the "you must join" prompt with one button per channel."""
    from config import PE_FLOWER, PE_LOCATION
    from utils.keyboards import style_btn, style_url

    unjoined = await get_unjoined_channels(bot, uid)
    if not unjoined:
        # Channels exist but none could be resolved (invite links, bot not
        # admin...).  Never trap the user behind a screen with no buttons.
        _remember(uid)
        return False

    remaining = len(unjoined)
    msg = (
        f"<blockquote>{PE_FLOWER} <b>\U0001D418\U0001D428\U0001D42E "
        f"\U0001D426\U0001D42E\U0001D42C\U0001D42D \U0001D428\U0001D422\U0001D427 "
        f"\U0001D428\U0001D42E\U0001D42B \U0001D41C\U0001D421\U0001D41A\U0001D427\U0001D427\U0001D41E\U0001D425\U0001D42C "
        f"& \U0001D420\U0001D42B\U0001D428\U0001D42E\U0001D429\U0001D42C "
        f"\U0001D41F\U0001D422\U0001D42B\U0001D42C\U0001D42D!</b></blockquote>\n"
        f"<blockquote>{PE_LOCATION} {remaining} "
        f"\U0001D41C\U0001D421\U0001D41A\U0001D427\U0001D427\U0001D41E\U0001D425\U0001D42C/"
        f"\U0001D420\U0001D42B\U0001D428\U0001D42E\U0001D429\U0001D42C "
        f"\U0001D42B\U0001D41E\U0001D426\U0001D41A\U0001D422\U0001D427\U0001D422\U0001D427\U0001D420. "
        f"\U0001D409\U0001D428\U0001D422\U0001D427 \U0001D41A\U0001D427\U0001D41D "
        f"\U0001D42D\U0001D41A\U0001D429 <b>\U0001D415\U0001D41E\U0001D42B\U0001D422"
        f"\U0001D41F\U0001D432 \U0001D409\U0001D428\U0001D422\U0001D427\U0001D41E\U0001D41D</b>."
        f"</blockquote>"
    )

    buttons = []
    for url, idx in unjoined:
        is_group = ("+" in url or "joinchat" in url or idx == 2)
        label = ("\U0001F4AC \U0001D409\U0001D428\U0001D422\U0001D427 "
                 "\U0001D406\U0001D42B\U0001D428\U0001D42E\U0001D429"
                 if is_group else
                 "\U0001F4E2 \U0001D409\U0001D428\U0001D422\U0001D427 "
                 "\U0001D402\U0001D421\U0001D41A\U0001D427\U0001D427\U0001D41E\U0001D425")
        buttons.append([style_url(label, url, "primary", icon=5409119256107297715)])
    buttons.append([style_btn(
        "\U0001D415\U0001D41E\U0001D42B\U0001D422\U0001D41F\U0001D432 "
        "\U0001D409\U0001D428\U0001D422\U0001D427\U0001D41E\U0001D41D",
        b"verify_join", "success", icon=6129627894349045589)])

    # Callbacks get an in-place edit (no message spam); plain messages get a
    # fresh reply.  Both paths fall back to text if the banner fails.
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.answer("\U0001F512 Please join our channels first.", alert=True)
        except Exception:
            pass
        try:
            await event.edit(msg, buttons=buttons)
            return True
        except Exception:
            pass
    try:
        await event.respond(msg, buttons=buttons)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FSub prompt could not be sent to %s: %s", uid, exc)
    return True


def register_fsub_guard(bot):
    """Install the guard.  Must be called BEFORE every other plugin."""

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out))
    async def fsub_guard_message(event):
        text = (event.raw_text or "").strip()
        if text.lower().startswith(SKIP_TEXTS):
            return
        uid = event.sender_id
        if not uid:
            return
        try:
            if await _needs_join(bot, uid):
                await _join_screen(bot, event, uid)
                raise events.StopPropagation
        except events.StopPropagation:
            raise
        except Exception as exc:  # noqa: BLE001 - never break normal chatting
            logger.warning("FSub guard (message) error for %s: %s", uid, exc)

    @bot.on(events.CallbackQuery())
    async def fsub_guard_callback(event):
        data = event.data or b""
        if data in SKIP_CALLBACKS:
            return
        uid = event.sender_id
        if not uid:
            return
        try:
            if await _needs_join(bot, uid):
                await _join_screen(bot, event, uid)
                raise events.StopPropagation
        except events.StopPropagation:
            raise
        except Exception as exc:  # noqa: BLE001 - never break normal buttons
            logger.warning("FSub guard (callback) error for %s: %s", uid, exc)

    logger.info("\U0001F6E1\uFE0F Force-subscribe guard installed (re-verifies every interaction)")
    return 2
