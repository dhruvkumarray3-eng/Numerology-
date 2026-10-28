"""More Content menu.

Implements the extra functions from the reference app:
  • Read & Generate Sessions
  • Redeem (code -> balance)
  • Refer & Earn (reuses existing referral menu)
  • Get your own Bots (external URL)
  • Back
"""
import html
from telethon import events, Button
from telethon.errors import MessageNotModifiedError

from config import (
    PE_GIFT,
    PE_CHECK,
    PE_LIGHTNING,
    UPDATES_URL,
    SUPPORT_URL,
    MAIN_CHANNEL_URL,
    logger,
)
from database import (
    cur, db, redeem_code_for_user, get_user_currency, create_redeem_code,
    list_redeem_codes, is_admin, get_source_codes,
)
from utils.keyboards import style_btn, style_url
from utils.session_gen import generate_session_from_string, read_session_file

# uid -> {"mode": "redeem"|"session"}
more_state = {}


async def show_more_content(event):
    uid = event.sender_id
    more_state.pop(uid, None)
    msg = (
        f"<blockquote expandable>{PE_GIFT} <b>📦 More Content</b>\n\n"
        f"🧩 <b>Read &amp; Generate Sessions</b> — convert a Telethon StringSession "
        f"into a .session file, or read an existing session.\n"
        f"🎟 <b>Redeem</b> — redeem a gift code and get balance instantly.\n"
        f"🎁 <b>Refer &amp; Earn</b> — invite friends and earn commission.\n"
        f"🤖 <b>Get the Best Bots</b> — bot news and updates.\n\n"
        f"<i>Choose an option below.</i></blockquote>"
    )
    btns = [
        [style_btn("🧩 Read & Generate Sessions", b"mc_sessions", "primary", icon=5409320020058584473)],
        [style_btn("🎟 Redeem", b"mc_redeem", "success", icon=5409098988156629257)],
        [style_btn("🎁 Refer & Earn", b"view_referrals", "success", icon=5354889508674360491)],
        # ---- Get the Best Bots (colourful link hub) ----
        [style_url("🤖 Get the Best Bots ↗️", UPDATES_URL, "success", icon=5409320020058584473)],
        [style_url("📢 Updates Channel ↗️", MAIN_CHANNEL_URL, "primary", icon=6129732880529628243)],
        [style_url("🛠 Bot Setup Support ↗️", SUPPORT_URL, "danger", icon=6129812419028982717)],
        [style_btn("🔙 Back", b"dashboard_main", "danger", icon=6129812419028982717)],
    ]
    if get_source_codes():
        btns.insert(
            4,
            [style_btn("🧩 Buy Source Codes", b"src_code_menu", "primary",
                       icon=5409098988156629257)],
        )
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)


async def show_sessions_menu(event):
    msg = (
        f"<blockquote expandable>{PE_LIGHTNING} <b>🧩 Read &amp; Generate Sessions</b>\n\n"
        f"Send me either:\n"
        f"• a <b>StringSession</b> (starts with <code>1</code> and is long), or\n"
        f"• an uploaded <b>.session</b> file.\n\n"
        f"I will convert it into a downloadable <code>.session</code> file.\n\n"
        f"<i>Your session is processed locally and never stored permanently.</i></blockquote>"
    )
    btns = [[style_btn("🔙 Back", b"mc_home", "danger", icon=6129812419028982717)]]
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)
    more_state[event.sender_id] = {"mode": "session"}


async def show_redeem_prompt(event):
    msg = (
        f"<blockquote expandable>{PE_GIFT} <b>🎟 Redeem a Code</b>\n\n"
        f"Send your redeem code in chat and I will credit the balance instantly.\n\n"
        f"<i>Codes are single-use unless stated otherwise.</i></blockquote>"
    )
    btns = [[style_btn("🔙 Back", b"mc_home", "danger", icon=6129812419028982717)]]
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)
    more_state[event.sender_id] = {"mode": "redeem"}


def register_more_content(bot):
    @bot.on(events.CallbackQuery(pattern=r"^more_content$"))
    async def cb_more_content(e):
        await show_more_content(e)

    @bot.on(events.CallbackQuery(pattern=r"^mc_home$"))
    async def cb_mc_home(e):
        await show_more_content(e)

    @bot.on(events.CallbackQuery(pattern=r"^mc_sessions$"))
    async def cb_mc_sessions(e):
        await show_sessions_menu(e)

    @bot.on(events.CallbackQuery(pattern=r"^mc_redeem$"))
    async def cb_mc_redeem(e):
        await show_redeem_prompt(e)

    @bot.on(events.NewMessage(pattern=r"^/addcode(?:@\w+)?\s+(\S+)\s+([0-9.]+)(?:\s+(\d+))?$"))
    async def cmd_addcode(e):
        if not is_admin(e.sender_id):
            return
        code = e.pattern_match.group(1)
        try:
            amount = float(e.pattern_match.group(2))
            max_uses = int(e.pattern_match.group(3) or 1)
        except ValueError:
            return await e.respond("❌ Usage: <code>/addcode CODE AMOUNT [MAX_USES]</code>")
        create_redeem_code(code, amount, max_uses)
        await e.respond(
            f"<blockquote>✅ <b>Redeem code created</b>\n"
            f"🎟 <b>Code:</b> <code>{html.escape(code)}</code>\n"
            f"💰 <b>Amount:</b> <code>{amount:.2f}</code>\n"
            f"🔁 <b>Max uses:</b> <code>{max_uses}</code></blockquote>"
        )

    @bot.on(events.NewMessage(pattern=r"^/codes$"))
    async def cmd_codes(e):
        if not is_admin(e.sender_id):
            return
        rows = list_redeem_codes()
        if not rows:
            return await e.respond("No redeem codes yet. Use <code>/addcode CODE AMOUNT</code>.")
        lines = [f"<code>{html.escape(c)}</code> — {a:.2f} ({u}/{m})" for c, a, m, u, act in rows]
        await e.respond("<blockquote><b>🎟 Redeem Codes</b>\n\n" + "\n".join(lines) + "</blockquote>")

    @bot.on(events.NewMessage(pattern=r"^/redeem(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_redeem(e):
        code = (e.pattern_match.group(1) or "").strip()
        if not code:
            return await show_redeem_prompt(e)
        ok, message, amount = redeem_code_for_user(code, e.sender_id)
        if ok:
            cur_code = get_user_currency(e.sender_id)
            await e.respond(
                f"<blockquote>{PE_CHECK} <b>{html.escape(message)}</b>\n"
                f"💰 <b>Credited:</b> <code>{amount:.2f} {cur_code}</code></blockquote>"
            )
        else:
            await e.respond(f"<blockquote>{html.escape(message)}</blockquote>")

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out))
    async def mc_text_router(e):
        """Handles redeem codes and string sessions typed in chat."""
        uid = e.sender_id
        state = more_state.get(uid)
        text = (e.text or "").strip()
        if not state or not text or text.startswith("/"):
            return
        mode = state.get("mode")

        if mode == "redeem":
            more_state.pop(uid, None)
            ok, message, amount = redeem_code_for_user(text, uid)
            if ok:
                cur_code = get_user_currency(uid)
                await e.respond(
                    f"<blockquote>{PE_CHECK} <b>{html.escape(message)}</b>\n"
                    f"💰 <b>Credited:</b> <code>{amount:.2f} {cur_code}</code></blockquote>",
                    buttons=[[style_btn("🔙 Back", b"mc_home", "primary")]],
                )
            else:
                await e.respond(
                    f"<blockquote>{html.escape(message)}</blockquote>",
                    buttons=[[style_btn("🔙 Back", b"mc_home", "primary")]],
                )
            raise events.StopPropagation

        if mode == "session":
            more_state.pop(uid, None)
            try:
                path, err = generate_session_from_string(text)
            except Exception as ex:
                logger.error(f"session gen failed: {ex}")
                path, err = None, str(ex)
            if path:
                await e.respond(
                    f"<blockquote>{PE_CHECK} <b>Session generated successfully!</b></blockquote>",
                    file=path,
                )
            else:
                await e.respond(
                    f"<blockquote>❌ <b>Could not generate session.</b>\n<code>{html.escape(str(err))}</code></blockquote>",
                    buttons=[[style_btn("🔙 Back", b"mc_home", "primary")]],
                )
            raise events.StopPropagation

    @bot.on(events.NewMessage(func=lambda e: e.is_private and e.document is not None))
    async def mc_document_router(e):
        """Handles uploaded .session files."""
        uid = e.sender_id
        state = more_state.get(uid)
        if not state or state.get("mode") != "session":
            return
        name = ""
        for attr in getattr(e.document, "attributes", []):
            if hasattr(attr, "file_name"):
                name = attr.file_name or ""
        if not name.lower().endswith(".session"):
            return
        more_state.pop(uid, None)
        try:
            data = await e.download_media(bytes)
            summary = read_session_file(data)
            await e.respond(
                f"<blockquote>{PE_CHECK} <b>Session file read successfully</b>\n\n"
                f"{html.escape(summary)}</blockquote>",
                buttons=[[style_btn("🔙 Back", b"mc_home", "primary")]],
            )
        except Exception as ex:
            await e.respond(f"<blockquote>❌ Could not read session: <code>{html.escape(str(ex))}</code></blockquote>")
        raise events.StopPropagation
