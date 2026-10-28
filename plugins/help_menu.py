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
        "📊 <b>/rates</b> — ʟɪᴠᴇ ᴘᴀɴᴇʟ ʀᴀᴛᴇꜱ\n"
        "📦 <b>/myhistory</b> — ʏᴏᴜʀ ᴏʀᴅᴇʀꜱ & ᴘᴀʏᴍᴇɴᴛꜱ\n"
        "🆔 <b>/myid</b> — ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ɪᴅ & ᴄᴏᴅᴇ\n"
        "💬 <b>/support</b> — ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ\n\n"
        f"👥 ꜱᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ: <a href='{support_url}'>{html.escape(support_handle)}</a>\n"
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
        "👑 <b>ᴀᴅᴍɪɴ & ᴏᴡɴᴇʀ — ᴄᴏᴍᴍᴀɴᴅ ʀᴇᴘᴏꜱɪᴛᴏʀʏ</b>\n"
        "<i>Every command available in this bot.</i>"
        "</blockquote>\n"

        "<blockquote expandable>"
        "👤 <b>ᴜꜱᴇʀ ᴄᴏᴍᴍᴀɴᴅꜱ</b>\n"
        "/start — ᴍᴀɪɴ ᴍᴇɴᴜ\n"
        "/menu — ʀᴇᴏᴘᴇɴ ᴘᴇʀᴍᴀɴᴇɴᴛ ᴋᴇʏʙᴏᴀʀᴅ\n"
        "/hide • /close — ᴄʟᴏꜱᴇ ᴋᴇʏʙᴏᴀʀᴅ\n"
        "/rates — ᴘᴀɴᴇʟ ʀᴀᴛᴇꜱ\n"
        "/redeem <code> — ʀᴇᴅᴇᴇᴍ ᴀ ɢɪғᴛ ᴄᴏᴅᴇ\n"
        "/myhistory — ᴏᴡɴ ʜɪꜱᴛᴏʀʏ\n"
        "/myid • /id — ᴏᴡɴ ɪᴅ & ᴄᴅ ɪᴅ\n"
        "/support — ᴄᴏɴᴛᴀᴄᴛ ᴛᴇᴀᴍ\n"
        "/help — ᴛʜɪꜱ ᴄᴀʀᴅ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "🧩 <b>ᴘʀᴏᴅᴜᴄᴛ ᴘᴀɴᴇʟꜱ</b>\n"
        "/whatsapp • /wa — ᴡʜᴀᴛꜱᴀᴘᴘ ᴏᴛᴘ ᴘᴀɴᴇʟ\n"
        "/numchange • /numberchange — ᴛɢ ɴᴜᴍʙᴇʀ ᴄʜᴀɴɢᴇ\n"
        "/allotp • /otp • /apps — ᴀʟʟ ᴀᴘᴘꜱ ᴏᴛᴘ ᴘᴀɴᴇʟ\n"
        "/panels • /products — ᴘʀᴏᴅᴜᴄᴛ ʜᴜʙ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "💰 <b>ᴘʀᴏғɪᴛ ᴇɴɢɪɴᴇ</b>\n"
        "/setmarkup <percent> — ᴘᴇʀᴄᴇɴᴛ ᴍᴀʀᴋᴜᴘ\n"
        "/setprofit <amount> <INR|USD> — ғɪxᴇᴅ ᴘʀᴏғɪᴛ\n"
        "/markup — ꜱʜᴏᴡ ᴄᴜʀʀᴇɴᴛ ᴄᴏɴғɪɢ\n"
        "/resetmarkup — ʀᴇꜱᴇᴛ ᴛᴏ ᴅᴇғᴀᴜʟᴛ (25%)"
        "</blockquote>\n"

        "<blockquote expandable>"
        "👥 <b>ᴜꜱᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ</b>\n"
        "/history <user_id> — ғᴜʟʟ ᴜꜱᴇʀ ʜɪꜱᴛᴏʀʏ (sqlite + ᴍᴏɴɢᴏ)\n"
        "/grant <user_id> <amount> — ᴄʀᴇᴅɪᴛ ʙᴀʟᴀɴᴄᴇ\n"
        "/addcode <code> <amount> [uses] — ᴄʀᴇᴀᴛᴇ ɢɪғᴛ ᴄᴏᴅᴇ\n"
        "/codes — ʟɪꜱᴛ ᴀʟʟ ɢɪғᴛ ᴄᴏᴅᴇꜱ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "📊 <b>ᴘᴀɴᴇʟ & ᴍᴏɴɪᴛᴏʀɪɴɢ</b>\n"
        "/panelstats — ᴏʀᴅᴇʀꜱ, ʀᴇᴠᴇɴᴜᴇ, ʀᴇᴀʟ ᴄᴏꜱᴛ & ᴘʀᴏғɪᴛ\n"
        "/panelsales [n] — ʟᴀꜱᴛ n ᴘᴀɴᴇʟ ᴏʀᴅᴇʀꜱ\n"
        "/panelbalance — ᴛᴇᴍᴘᴏʀᴀꜱᴍꜱ ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ\n"
        "/mongostatus — ᴍᴏɴɢᴏᴅʙ ᴄᴏɴɴᴇᴄᴛɪᴏɴ + ᴄᴏᴜɴᴛꜱ"
        "</blockquote>\n"

        "<blockquote expandable>"
        "⚙️ <b>ꜱᴇᴛᴛɪɴɢꜱ</b>\n"
        "/admin — ғᴜʟʟ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ (ꜱᴛᴏᴄᴋ, ʙᴀɴ, ʙᴀʟᴀɴᴄᴇ, ʙʀᴏᴀᴅᴄᴀꜱᴛ, ʟᴇғᴛ...)\n"
        "/setchangefee <n> — ɴᴜᴍʙᴇʀ ᴄʜᴀɴɢᴇ ғᴇᴇ\n"
        "/lztmargin <n> • /setlztmargin <n> — ʟᴢᴛ ᴍᴀʀᴋᴜᴘ ᴘᴇʀ ɪᴛᴇᴍ\n"
        "/setsticker — ꜱᴇᴛ ᴛʜᴇ ꜱᴛᴀʀᴛ ꜱᴛɪᴄᴋᴇʀ\n"
        "/setpack flags|apps|misc [pack-link] — learn a premium emoji pack per role\n"
        "/packsync [flags|apps|misc] — re-sync one or all emoji packs\n"
        "/pack — emoji pack status (flags • apps • purchase)\n"
        "/packtest [name] [role] — preview a premium emoji\n"
        "/packmode off|country|all — when emojis are sent\n"
        "/mapsticker [name] — reply to an emoji to pin it for a name"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F9F9 <b>\u1d04\u029f\u1d07\u1d00\u0274\u1d1c\u1d18 & \u1d05\u1d07\u029f\u1d07\u1d1b\u1d07 \u1d04\u1d07\u0274\u1d1b\u1d07\u0280</b>\n"
        "/admin \u2192 \U0001F5D1 Cleanup & Delete \u2014 open the delete center\n"
        "\u2022 Delete OLD account stock (7 / 30 / 90 / 365 days)\n"
        "\u2022 Delete SOLD / unavailable stock only\n"
        "\u2022 Delete ALL stock (fresh start)\n"
        "\u2022 Delete a single panel or ALL panels\n"
        "\u2022 Delete a single source code or ALL source codes\n"
        "Every delete asks for confirmation first \u2014 nothing is removed by accident"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\u2728 <b>\u1d18\u0280\u1d07\u1d0d\u026a\u1d1c\u1d0d \u1d07\u1d0d\u1d0f\u1d0a\u026a & \ua731\u1d0d\u1d0d</b>\n"
        "/premiumcheck \u2014 diagnose why premium emojis do/don't render\n"
        "/markup \u2014 show the current profit engine (mode, %, fixed)\n"
        "/setprofit <n> \u2014 add a flat \u20b9 profit on top of panel price\n"
        "/setmarkup <pct> \u2014 add a % profit on top of panel price\n"
        "/resetmarkup \u2014 back to default profit\n"
        "/profit \u2014 open the Profit & Pricing panel (INR \u00b7 USDT \u00b7 per-service)\n"
        "/smm \u2014 SMM services (FathersMM). User price = panel rate + your profit"
        "</blockquote>\n"

        "<blockquote expandable>"
        "📩 <b>ꜱᴜᴘᴘᴏʀᴛ</b>\n"
        f"👥 ꜱᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ: <a href='{support_url}'>{html.escape(support_handle)}</a>\n"
        f"👑 ᴏᴡɴᴇʀ: <a href='{owner_url}'>{html.escape(owner_handle)}</a>"
        "</blockquote>"
    )


def _user_buttons():
    support_url, _ = _support_handle()
    owner_url, owner_handle = _owner_handle()
    return [
        [style_btn("\U0001F3E0 \u1d0d\u1d00\u026a\u0274 \u1d0d\u1d07\u0274\u1d1c", b"dashboard_main", "success", icon=5409320020058584473)],
        [style_url("\U0001F4AC \ua731\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b", support_url, "primary", icon=6129732880529628243)],
        [style_url("\U0001F451 \u1d0f\u1d21\u0274\u1d07\u0280", owner_url, "primary", icon=5409098988156629257)],
    ]


def _admin_buttons():
    return [
        [style_btn("\U0001F6E0 \u1d00\u1d05\u1d0d\u026a\u0274 \u1d18\u1d00\u0274\u1d07\u029f", b"help_open_admin", "success", icon=ADMIN_ICON)],
        [style_btn("\U0001F5D1 \u1d04\u029f\u1d07\u1d00\u0274\u1d1c\u1d18 & \u1d05\u1d07\u029f\u1d07\u1d1b\u1d07", b"ac_menu", "danger", icon=5408832111773757273)],
        [style_btn("\U0001F464 \u1d1c\ua731\u1d07\u0280 \u1d20\u026a\u1d07\u1d21", b"help_user", "primary", icon=USER_ICON),
         style_btn("\U0001F504 \u0280\u1d07\u0493\u0280\u1d07\ua731\u029c", b"help_main", "primary", icon=5409098988156629257)],
        [style_btn("\U0001F519 \u0299\u1d00\u1d04\u1d0b", b"dashboard_main", "danger", icon=BACK_ICON)],
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


    @bot.on(events.NewMessage(pattern=r"(?i)^/premiumcheck(?:@\w+)?$"))
    async def cmd_premiumcheck(e):
        """Diagnose why custom (premium) emojis may not render."""
        uid = getattr(e, "sender_id", None)
        if not (uid and _is_staff(uid)):
            return await e.respond("\u26d4 Admin only.")
        try:
            from config import USE_PREMIUM_EMOJIS
            from utils.keyboards import PREMIUM_ICONS, resolve_icon, pe
            import telethon
            from telethon.extensions import html as _thtml
            from telethon.tl.types import MessageEntityCustomEmoji

            sample_id = PREMIUM_ICONS.get("crown") or next(iter(PREMIUM_ICONS.values()))
            parsed_text, entities = _thtml.parse(
                f'x <tg-emoji emoji-id="{sample_id}">\u2b50</tg-emoji> y'
            )
            html_ok = any(isinstance(en, MessageEntityCustomEmoji) for en in entities)
            icon_ok = resolve_icon("crown") == sample_id

            lines = [
                "\U0001F50D <b>Premium Emoji Diagnostic</b>",
                "",
                f"\u2022 USE_PREMIUM_EMOJIS: <b>{'ON' if USE_PREMIUM_EMOJIS else 'OFF'}</b>",
                f"\u2022 Telethon version: <code>{telethon.__version__}</code>",
                f"\u2022 Button icon resolve: <b>{'OK' if icon_ok else 'FAIL'}</b>",
                f"\u2022 Message <tg-emoji> parse: <b>{'OK' if html_ok else 'FAIL'}</b>",
                f"\u2022 Registry size: <b>{len(PREMIUM_ICONS)}</b> icons",
                "",
                "<b>Why emojis may still not show:</b>",
                "Telegram only renders <b>custom emoji</b> (in buttons and messages) for bots whose "
                "<b>owner has an active Telegram Premium</b> subscription, or whose bot owns a "
                "<b>username bought on Fragment</b>. If your owner account has no Premium, the same "
                "code will show normal emojis \u2014 that is a Telegram rule, not a bot bug.",
                "",
                "<i>Fix: enable Telegram Premium on the account that created this bot (or buy a "
                "Fragment username for the bot), then restart the bot.</i>",
            ]
            await e.respond("\n".join(lines))
        except Exception as exc:
            logger.error(f"/premiumcheck error: {exc}", exc_info=True)
            await e.respond(f"\u274c premiumcheck failed: <code>{exc}</code>")
