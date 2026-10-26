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
        "\U0001F198 <b>\u1d07\u1d00\u0280\u1d0f\u1d0d\u1d07\u1d0e \u029c\u1d07\u029f\u1d18 \u1d04\u1d07\u0274\u1d1b\u1d07\u0280</b>\n\n"
        "\U0001F3E0 <b>/start</b> \u2014 \u1d0f\u1d18\u1d07\u0274 \u1d1b\u029c\u1d07 \u1d0d\u1d00\u026a\u0274 \u1d0d\u1d07\u0274\u1d1c\n"
        "\U0001F4CA <b>/rates</b> \u2014 \u029f\u026a\u1d20\u1d07 \u1d18\u1d00\u0274\u1d07\u029f \u0280\u1d00\u1d1b\u1d07s\n"
        "\U0001F4E6 <b>/myhistory</b> \u2014 \u028f\u1d0f\u1d1c\u0280 \u1d0f\u0280\u1d05\u1d07\u0280s &amp; \u1d18\u1d00\u028f\u1d0d\u1d07\u0274\u1d1bs\n"
        "\U0001F194 <b>/myid</b> \u2014 \u028f\u1d0f\u1d1c\u0280 \u1d1b\u1d07\u029f\u1d07\u0262\u0280\u1d00\u1d0d \u026a\u1d05 &amp; \u1d04\u1d0f\u1d05\u1d07\n"
        "\U0001F4AC <b>/support</b> \u2014 \u1d04\u1d0f\u0274\u1d1b\u1d00\u1d04\u1d1b \u029c\u1d07\u029f\u1d18\n\n"
        f"\U0001F465 \u1d05\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b \u0262\u0280\u1d0f\u1d1c\u1d18: <a href='{support_url}'>{html.escape(support_handle)}</a>\n"
        f"\U0001F451 \u1d0f\u1d21\u0274\u1d07\u0280: <a href='{owner_url}'>{html.escape(owner_handle)}</a>"
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
        "\U0001F451 <b>\u1d00\u1d05\u1d0d\u026a\u0274 &amp; \u1d0f\u1d21\u0274\u1d07\u0280 \u2014 \u1d04\u1d0f\u1d0d\u1d0d\u1d00\u0274\u1d05 \u0280\u1d07\u1d18\u1d07\u0280\u1d1b\u1d0f\u026a\u0280\u028f</b>\n"
        "<i>Every command available in this bot.</i>"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F464 <b>\u1d1c\u1d07\u0280 \u1d04\u1d0f\u1d0d\u1d0d\u1d00\u0274\u1d05\u1d05</b>\n"
        "/start \u2014 \u1d0d\u1d00\u026a\u0274 \u1d0d\u1d07\u0274\u1d1c\n"
        "/menu \u2014 \u0280\u1d07\u1d0f\u1d18\u1d07\u0274 \u1d18\u1d07\u0280\u0274\u1d00\u0274\u1d07\u0274\u1d1b \u1d0b\u1d07\u028f\u1d0d\u1d0f\u1d00\u0280\u1d05\n"
        "/hide \u2022 /close \u2014 \u1d04\u029f\u1d0f\u0282\u1d07 \u1d0b\u1d07\u028f\u1d0d\u1d0f\u1d00\u0280\u1d05\n"
        "/rates \u2014 \u1d18\u1d00\u0274\u1d07\u029f \u0280\u1d00\u1d1b\u1d07s\n"
        "/redeem &lt;code&gt; \u2014 \u0280\u1d07\u1d05\u1d07\u1d07\u1d0d \u1d00 \u0262\u026a\u0493\u1d1b \u1d04\u1d0f\u1d05\u1d07\n"
        "/myhistory \u2014 \u1d0f\u1d21\u0274 \u029c\u026a\u0282\u1d1b\u1d0f\u0280\u028f\n"
        "/myid \u2022 /id \u2014 \u1d0f\u1d21\u0274 \u026a\u1d05 &amp; \u1d04\u1d05 \u026a\u1d05\n"
        "/support \u2014 \u1d04\u1d0f\u0274\u1d1b\u1d00\u1d04\u1d1b \u1d1b\u1d07\u1d00\u1d0d\n"
        "/help \u2014 \u1d1b\u029c\u026a\u1d05 \u1d04\u1d00\u0280\u1d05"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F9E9 <b>\u1d18\u1d05\u1d0f\u1d05\u1d1c\u1d04\u1d1b \u1d18\u1d00\u0274\u1d07\u029f\u1d05</b>\n"
        "/whatsapp \u2022 /wa \u2014 \u1d21\u029c\u1d00\u1d1b\u1d05\u1d00\u1d18\u1d18 \u1d0f\u1d1b\u1d18 \u1d18\u1d00\u0274\u1d07\u029f\n"
        "/numchange \u2022 /numberchange \u2014 \u1d1b\u0262 \u0274\u1d1c\u1d0d\u0299\u1d07\u0280 \u1d04\u029c\u1d00\u0274\u0262\u1d07\n"
        "/allotp \u2022 /otp \u2022 /apps \u2014 \u1d00\u029f\u029f \u1d00\u1d18\u1d18\u1d05 \u1d0f\u1d1b\u1d18 \u1d18\u1d00\u0274\u1d07\u029f\n"
        "/panels \u2022 /products \u2014 \u1d18\u1d05\u1d0f\u1d05\u1d1c\u1d04\u1d1b \u029c\u1d1c\u0299"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F4B0 <b>\u1d18\u0280\u1d0f\u0493\u026a\u1d1b \u1d07\u0274\u0262\u026a\u0274\u1d07</b>\n"
        "/setmarkup &lt;percent&gt; \u2014 \u1d18\u1d07\u0280\u1d04\u1d07\u0274\u1d1b \u1d0d\u1d00\u0280\u1d0b\u1d1c\u1d18\n"
        "/setprofit &lt;amount&gt; &lt;INR|USD&gt; \u2014 \u0493\u026a\u1d05\u1d07\u1d05 \u1d18\u0280\u1d0f\u0493\u026a\u1d1b\n"
        "/markup \u2014 \u0282\u029c\u1d0f\u1d21 \u1d04\u1d1c\u0280\u0280\u1d07\u0274\u1d1b \u1d04\u1d0f\u0274\u0493\u026a\u0262\n"
        "/resetmarkup \u2014 \u0280\u1d07\u0282\u1d07\u1d1b \u1d1b\u1d0f \u1d05\u1d07\u0493\u1d00\u1d1c\u029f\u1d1b (25%)"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F465 <b>\u1d1c\u1d07\u0280 \u1d0d\u1d00\u0274\u1d00\u0262\u1d07\u1d0d\u1d07\u0274\u1d1b</b>\n"
        "/history &lt;user_id&gt; \u2014 \u0493\u1d1c\u029f\u029f \u1d1c\u1d07\u0280 \u029c\u026a\u0282\u1d1b\u1d0f\u0280\u028f (\u1d05\u1d20\u029f\u026a\u1d1b\u1d07 + \u1d0d\u1d0f\u0274\u0262\u1d0f)\n"
        "/grant &lt;user_id&gt; &lt;amount&gt; \u2014 \u1d04\u0280\u1d07\u1d05\u026a\u1d1b \u0299\u1d00\u029f\u1d00\u0274\u1d04\u1d07\n"
        "/addcode &lt;code&gt; &lt;amount&gt; [uses] \u2014 \u1d04\u0280\u1d07\u1d00\u1d1b\u1d07 \u0262\u026a\u0493\u1d1b \u1d04\u1d0f\u1d05\u1d07\n"
        "/codes \u2014 \u029f\u026a\u0282\u1d1b \u1d00\u029f\u029f \u0262\u026a\u0493\u1d1b \u1d04\u1d0f\u1d05\u1d07\u1d05"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F4CA <b>\u1d18\u1d00\u0274\u1d07\u029f &amp; \u1d0d\u1d0f\u0274\u026a\u1d1b\u1d0f\u0280\u026a\u0274\u0262</b>\n"
        "/panelstats \u2014 \u1d0f\u0280\u1d05\u1d07\u0280\u1d05, \u0280\u1d07\u1d20\u1d07\u0274\u1d1c\u1d07, \u0280\u1d07\u1d00\u029f \u1d04\u1d0f\u1d05\u1d1b &amp; \u1d18\u0280\u1d0f\u0493\u026a\u1d1b\n"
        "/panelsales [n] \u2014 \u029f\u1d00\u1d05\u1d1b n \u1d18\u1d00\u0274\u1d07\u029f \u1d0f\u0280\u1d05\u1d07\u0280\u1d05\n"
        "/panelbalance \u2014 \u1d1b\u1d07\u1d0d\u1d18\u1d0f\u0280\u1d00\u1d05\u1d0d\u1d05 \u1d21\u1d00\u029f\u029f\u1d07\u1d1b \u0299\u1d00\u029f\u1d00\u0274\u1d04\u1d07\n"
        "/mongostatus \u2014 \u1d0d\u1d0f\u0274\u0262\u1d0f\u1d05\u1d05 \u1d04\u1d0f\u0274\u0274\u1d07\u1d04\u1d1b\u026a\u1d0f\u0274 + \u1d04\u1d0f\u1d1c\u0274\u1d1b\u1d05"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\u2699\uFE0F <b>\u1d05\u1d07\u1d1b\u1d1b\u026a\u0274\u0262\u1d05</b>\n"
        "/admin \u2014 \u0493\u1d1c\u029f\u029f \u1d00\u1d05\u1d0d\u026a\u0274 \u1d18\u1d00\u0274\u1d07\u029f (\u1d05\u1d1b\u1d0f\u1d04\u1d0b, \u0299\u1d00\u0274, \u0299\u1d00\u029f\u1d00\u0274\u1d04\u1d07, \u0299\u0280\u1d0f\u1d00\u1d05\u1d04\u1d00\u1d05\u1d1b, \u029f\u1d07\u1d18\u1d1b...)\n"
        "/setchangefee &lt;n&gt; \u2014 \u0274\u1d1c\u1d0d\u0299\u1d07\u0280 \u1d04\u029c\u1d00\u0274\u0262\u1d07 \u0493\u1d07\u1d07\n"
        "/lztmargin &lt;n&gt; \u2022 /setlztmargin &lt;n&gt; \u2014 \u029f\u1d22\u1d1b \u1d0d\u1d00\u0280\u1d0b\u1d1c\u1d18 \u1d18\u1d07\u0280 \u026a\u1d1b\u1d07\u1d0d\n"
        "/setsticker \u2014 \u1d05\u1d07\u1d1b \u1d1b\u029c\u1d07 \u1d05\u1d1b\u1d00\u0280\u1d1b \u1d05\u1d1b\u026a\u1d04\u1d0b\u1d07\u0280"
        "/setpack [pack-link] \u2014 learn a premium sticker pack (countries + apps)\n"
        "/pack \u2022 /packsync \u2014 sticker pack status / re-sync\n"
        "/packmode off|country|all \u2014 when stickers are sent\n"
        "/mapsticker [name] \u2014 reply to a sticker to pin it for a name"
        "</blockquote>\n"

        "<blockquote expandable>"
        "\U0001F4E9 <b>\u1d05\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b</b>\n"
        f"\U0001F465 \u1d05\u1d1c\u1d18\u1d18\u1d0f\u0280\u1d1b \u0262\u0280\u1d0f\u1d1c\u1d18: <a href='{support_url}'>{html.escape(support_handle)}</a>\n"
        f"\U0001F451 \u1d0f\u1d21\u0274\u1d07\u0280: <a href='{owner_url}'>{html.escape(owner_handle)}</a>"
        "</blockquote>"
    )


# ---------------------------------------------------------------------------
# senders
# ---------------------------------------------------------------------------
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
