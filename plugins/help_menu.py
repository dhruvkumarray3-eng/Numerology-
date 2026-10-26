"""Central /help menu.

- Normal users get a short, clean help card with only 5 essential commands.
- Admins / owners get the FULL command reference (every command in the bot),
  grouped by category, plus quick buttons to jump into the admin panel.

Callbacks:
    help_main    -> entry point (auto-detects admin vs user)
    help_user    -> force the user card
    help_admin   -> force the admin/owner card
"""

import html

from telethon import events

from config import ADMIN_ID, is_super_admin, logger
from database import is_admin, get_support_url
from utils.keyboards import style_btn, style_url


HELP_ICON = 6129732880529628243
BACK_ICON = 6129812419028982717
ADMIN_ICON = 5409098988156629257
USER_ICON = 6203982793379154737


# ---------------------------------------------------------------------------
# permission helpers
# ---------------------------------------------------------------------------
def _is_owner(uid):
    try:
        return bool(is_super_admin(uid))
    except Exception:
        return uid == ADMIN_ID


def _is_staff(uid):
    if _is_owner(uid):
        return True
    try:
        return bool(is_admin(uid))
    except Exception:
        return False


def _support_handle():
    try:
        url = get_support_url()
    except Exception:
        url = "https://t.me/usersupportgroupby_vendors"
    if url.startswith("https://t.me/"):
        return url, "@" + url.split("/")[-1]
    return url, url


# ---------------------------------------------------------------------------
# user card (3 - 5 commands only)
# ---------------------------------------------------------------------------
def _owner_handle():
    try:
        from config import OWNER_URL, OWNER_USERNAME
    except Exception:
        OWNER_URL, OWNER_USERNAME = "https://t.me/Vendor_masterz", "@Vendor_masterz"
    return OWNER_URL, OWNER_USERNAME


def _user_help_text():
    support_url, support_handle = _support_handle()
    owner_url, owner_handle = _owner_handle()
    return (
        "<blockquote expandable>"
        "🆘 <b>ᴡᴇʟᴄᴏᴍᴇ ʜᴇʟᴘ ᴄᴇɴᴛᴇʀ</b>\n\n"
        "🏠 <b>/start</b> — ᴏᴘᴇɴ ᴛʜᴇ ᴍᴀɪɴ ᴍᴇɴᴜ\n"
        "📊 <b>/rates</b> — ʟɪᴠᴇ ᴘᴀɴᴇʟ ʀᴀᴛᴇʂ\n"
        "📦 <b>/myhistory</b> — ʏᴏᴜʀ ᴏʀᴅᴇʀʂ & ᴘᴀʏᴍᴇɴᴛʂ\n"
        "🆔 <b>/myid</b> — ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ɪᴅ & ᴄᴏᴅᴇ\n"
        "💬 <b>/support</b> — ᴄᴏɴᴛᴀᴄᴛ ʂᴜᴘᴘᴏʀᴛ\n\n"
        f"👥 ʂᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ: <a href='{support_url}'>{html.escape(support_handle)}</a>\n"
        f"👑 ᴏᴡɴᴇʀ: <a href='{owner_url}'>{html.escape(owner_handle)}</a>"
        "</blockquote>"
    )


# ---------------------------------------------------------------------------
# admin / owner card (EVERY command in the bot)
# ---------------------------------------------------------------------------
def _admin_help_text():
    support_url, support_handle = _support_handle()
    owner_url, owner_handle = _owner_handle()
    return (
        "<blockquote expandable>"
        "👑 <b>ᴀᴅᴍɪɴ & ᴏᴡɴᴇʀ — ᴄᴏᴍᴍᴀɴᴅ ʀᴇᴘᴏʂɪᴛᴏʀʏ</b>\n"
        "<i>Every command available in this bot.</i>"
        "</blockquote>\n"

        "<blockquote expandable>"
        "👤 <b>ᴜʂᴇʀ ᴄᴏᴍᴍᴀɴᴅʂ</b>\n"
        "/start — ᴍᴀɪɴ ᴍᴇɴᴜ\n"
        "/menu — ʀᴇᴏᴘᴇɴ ᴘᴇʀᴍᴀɴᴇɴᴛ ᴋᴇʏʙᴏᴀʀᴅ\n"
        "/hide • /close — ᴄʟᴏʂᴇ ᴋᴇʏʙᴏᴀʀᴅ\n"
        "/rates — ᴘᴀɴᴇʟ ʀᴀᴛᴇʂ\n"
        "/redeem <code> — ʀᴇᴅᴇᴇᴍ ᴀ ɢɪғᴛ ᴄᴏᴅᴇ\n"
        "/myhistory — ᴏᴡɴ ʜɪʂᴛᴏʀʏ\n"
        "/myid • /id — ᴏᴡɴ ɪᴅ & ᴄᴅ ɪᴅ\n"
        "/support — ᴄᴏɴᴛᴀᴄᴛ ᴛᴇᴀᴍ\n"
        "/help — ᴛʜɪʂ ᴄᴀʀᴅ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "🧩 <b>ᴘʀᴏᴅᴜᴄᴛ ᴘᴀɴᴇʟʂ</b>\n"
        "/whatsapp • /wa — ᴡʜᴀᴛʂᴀᴘᴘ ᴏᴛᴘ ᴘᴀɴᴇʟ\n"
        "/numchange • /numberchange — ᴛɢ ɴᴜᴍʙᴇʀ ᴄʜᴀɴɢᴇ\n"
        "/allotp • /otp • /apps — ᴀʟʟ ᴀᴘᴘʂ ᴏᴛᴘ ᴘᴀɴᴇʟ\n"
        "/panels • /products — ᴘʀᴏᴅᴜᴄᴛ ʜᴜʙ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "💰 <b>ᴘʀᴏғɪᴛ ᴇɴɢɪɴᴇ</b>\n"
        "/setmarkup <percent> — ᴘᴇʀᴄᴇɴᴛ ᴍᴀʀᴋᴜᴘ\n"
        "/setprofit <amount> <INR|USD> — ғɪxᴇᴅ ᴘʀᴏғɪᴛ\n"
        "/markup — ʂʜᴏᴡ ᴄᴜʀʀᴇɴᴛ ᴄᴏɴғɪɢ\n"
        "/resetmarkup — ʀᴇʂᴇᴛ ᴛᴏ ᴅᴇғᴀᴜʟᴛ (25%)"
        "</blockquote>\n"

        "<blockquote expandable>"
        "👥 <b>ᴜʂᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ</b>\n"
        "/history <user_id> — ғᴜʟʟ ᴜʂᴇʀ ʜɪʂᴛᴏʀʏ (sqlite + ᴍᴏɴɢᴏ)\n"
        "/grant <user_id> <amount> — ᴄʀᴇᴅɪᴛ ʙᴀʟᴀɴᴄᴇ\n"
        "/addcode <code> <amount> [uses] — ᴄʀᴇᴀᴛᴇ ɢɪғᴛ ᴄᴏᴅᴇ\n"
        "/codes — ʟɪʂᴛ ᴀʟʟ ɢɪғᴛ ᴄᴏᴅᴇʂ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "📊 <b>ᴘᴀɴᴇʟ & ᴍᴏɴɪᴛᴏʀɪɴɢ</b>\n"
        "/panelstats — ᴏʀᴅᴇʀʂ, ʀᴇᴠᴇɴᴜᴇ, ʀᴇᴀʟ ᴄᴏʂᴛ & ᴘʀᴏғɪᴛ\n"
        "/panelsales [n] — ʟᴀʂᴛ n ᴘᴀɴᴇʟ ᴏʀᴅᴇʀʂ\n"
        "/panelbalance — ᴛᴇᴍᴘᴏʀᴀʂᴍʂ ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ\n"
        "/mongostatus — ᴍᴏɴɢᴏᴅʙ ᴄᴏɴɴᴇᴄᴛɪᴏɴ + ᴄᴏᴜɴᴛʂ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "⚙️ <b>ʂᴇᴛᴛɪɴɢʂ</b>\n"
        "/admin — ғᴜʟʟ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ (ʂᴛᴏᴄᴋ, ʙᴀɴ, ʙᴀʟᴀɴᴄᴇ, ʙʀᴏᴀᴅᴄᴀʂᴛ, ʟᴇғᴛ...)\n"
        "/setchangefee <n> — ɴᴜᴍʙᴇʀ ᴄʜᴀɴɢᴇ ғᴇᴇ\n"
        "/lztmargin <n> • /setlztmargin <n> — ʟᴢᴛ ᴍᴀʀᴋᴜᴘ ᴘᴇʀ ɪᴛᴇᴍ\n"
        "/setsticker — ʂᴇᴛ ᴛʜᴇ ʂᴛᴀʀᴛ ʂᴛɪᴄᴋᴇʀ\n"
        "/setpack flags|apps|misc [pack-link] — learn a premium emoji pack per role\n"
        "/packsync [flags|apps|misc] — re-sync one or all emoji packs\n"
        "/pack — emoji pack status (flags • apps • purchase)\n"
        "/packtest [name] [role] — preview a premium emoji\n"
        "/packmode off|country|all — when emojis are sent\n"
        "/mapsticker [name] — reply to an emoji to pin it for a name"
        "</blockquote>\n"

        "<blockquote expandable>"
        "📩 <b>ʂᴜᴘᴘᴏʀᴛ</b>\n"
        f"👥 ʂᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ: <a href='{support_url}'>{html.escape(support_handle)}</a>\n"
        f"👑 ᴏᴡɴᴇʀ: <a href='{owner_url}'>{html.escape(owner_handle)}</a>"
        "</blockquote>"
    )


def _user_buttons():
    support_url, _ = _support_handle()
    owner_url, owner_handle = _owner_handle()
    return [
        [style_btn("\U0001F3E0 \u1d0d\u1d00\u026a\u0274 \u1d0d\u1d07\u0274\u1d1c", b"dashboard_main", "success", icon=5409320020058584473)],
        [style_url("\U0001F4AC \u1d05\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b", support_url, "primary", icon=6129732880529628243)],
        [style_url("\U0001F451 \u1d0f\u1d21\u0274\u1d07\u0280", owner_url, "primary", icon=5409098988156629257)],
    ]


def _admin_buttons():
    return [
        [style_btn("\U0001F6E0 \u1d00\u1d05\u1d0d\u026a\u0274 \u1d18\u1d00\u0274\u1d07\u029f", b"help_open_admin", "success", icon=ADMIN_ICON)],
        [style_btn("\U0001F464 \u1d1c\u1d07\u0280 \u1d20\u026a\u1d07\u1d21", b"help_user", "primary", icon=USER_ICON),
         style_btn("\U0001F504 \u0280\u1d07\u0493\u0280\u1d07\u0282\u029c", b"help_main", "primary", icon=5409098988156629257)],
        [style_btn("\U0001F519 \u1d05\u1d00\u1d04\u1d0b", b"dashboard_main", "danger", icon=BACK_ICON)],
    ]


async def _safe_send(event, text, buttons):
    try:
        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons, link_preview=False)
        else:
            await event.respond(text, buttons=buttons, link_preview=False)
    except Exception as exc:
        logger.warning(f"help send failed: {exc}")
        try:
            await event.respond(text, buttons=buttons, link_preview=False)
        except Exception:
            pass


async def show_user_help(event):
    await _safe_send(event, _user_help_text(), _user_buttons())


async def show_admin_help(event):
    await _safe_send(event, _admin_help_text(), _admin_buttons())


async def show_help(event):
    """Auto-detect: admins/owners get the full reference, users get 5 commands."""
    uid = getattr(event, "sender_id", None)
    if uid and _is_staff(uid):
        return await show_admin_help(event)
    return await show_user_help(event)


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------
def register_help(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/(help|commands|cmds)(?:@\w+)?$"))
    async def cmd_help(e):
        try:
            await show_help(e)
        except Exception as exc:
            logger.error(f"/help error: {exc}", exc_info=True)

    @bot.on(events.NewMessage(pattern=r"(?i)^\U0001F198\s*help$"))
    async def msg_help_button(e):
        try:
            await show_help(e)
        except Exception as exc:
            logger.error(f"help button error: {exc}", exc_info=True)

    @bot.on(events.CallbackQuery(pattern=r"^help_main$"))
    async def cb_help_main(e):
        await e.answer()
        await show_help(e)

    @bot.on(events.CallbackQuery(pattern=r"^help_user$"))
    async def cb_help_user(e):
        await e.answer()
        await show_user_help(e)

    @bot.on(events.CallbackQuery(pattern=r"^help_admin$"))
    async def cb_help_admin(e):
        uid = e.sender_id
        if not _is_staff(uid):
            await e.answer("\u26d4 Admin only.", alert=True)
            return
        await e.answer()
        await show_admin_help(e)

    @bot.on(events.CallbackQuery(pattern=r"^help_open_admin$"))
    async def cb_help_open_admin(e):
        uid = e.sender_id
        if not _is_staff(uid):
            await e.answer("\u26d4 Admin only.", alert=True)
            return
        await e.answer()
        from plugins.admin import admin_panel_handler
        await admin_panel_handler(e)
