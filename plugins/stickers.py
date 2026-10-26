"""Premium sticker / custom-emoji admin surface.

Three packs are supported:

    flags  ->  world-flag custom emoji   (t.me/addemoji/FlagsEmoji2024)
    apps   ->  app-logo custom emoji     (t.me/addemoji/ApplicationEmoji)
    misc   ->  purchase / success emoji  (t.me/addemoji/exppwebs_by_fStikBot)

Commands (admins only):
    /setpack <link>              -> connect the flags pack (legacy form)
    /setpack flags|apps|misc <link>
                                 -> connect a specific pack
    /pack                        -> status of all three packs
    /packsync [flags|apps|misc]  -> force re-download (all when no role)
    /packmode off|country|all    -> when stickers are sent
    /packtest <name> [role]      -> preview which emoji a name resolves to
    /mapsticker <name>           -> reply to a sticker/emoji to pin it
    /unmapsticker <name>         -> drop a manual override
    /packmap                     -> list manual overrides

Everything is defensive: a broken pack never breaks the bot.
"""
import html

from telethon import events

from config import (
    ADMIN_ID,
    logger,
    PE_CROWN, PE_CHECK, PE_GIFT, PE_LIGHTNING, PE_STAR, PE_TAG, PE_ID,
)
from database import is_admin
from utils.keyboards import style_btn
from utils import stickers


def _is_admin(uid):
    try:
        return bool(is_admin(uid)) or bool(ADMIN_ID and uid == ADMIN_ID)
    except Exception:
        return bool(ADMIN_ID and uid == ADMIN_ID)


def _mode_label(mode):
    return {
        "off": "\U0001F6AB Off",
        "country": "\U0001F30D Country only",
        "all": "\U0001F30D Country + \U0001F4F1 Apps",
    }.get(mode, mode)


def _role_icon(role):
    return {"flags": "\U0001F3F3\uFE0F", "apps": "\U0001F4F1", "misc": "\U0001F389"}.get(role, "\u2B50")


async def _reply(event, text, buttons=None):
    try:
        await event.respond(text, buttons=buttons, parse_mode="html")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"stickers reply failed: {exc}")


def _parse_setpack_args(arg):
    """Return (role, short_name) from '/setpack [role] <link>'."""
    arg = (arg or "").strip()
    if not arg:
        return "", ""
    parts = arg.split(None, 1)
    if parts[0].lower() in stickers.ROLES and len(parts) == 2:
        return parts[0].lower(), stickers.parse_pack_link(parts[1])
    return "flags", stickers.parse_pack_link(arg)


def register_stickers(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/setpack(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_setpack(e):
        if not _is_admin(e.sender_id):
            return
        arg = (e.pattern_match.group(1) or "").strip()
        if not arg:
            return await _reply(
                e,
                f"<blockquote>{PE_TAG} <b>Connect a Premium Emoji Pack</b>\n\n"
                "Send a pack link with its role:\n"
                "<code>/setpack flags https://t.me/addemoji/FlagsEmoji2024</code>\n"
                "<code>/setpack apps https://t.me/addemoji/ApplicationEmoji</code>\n"
                "<code>/setpack misc https://t.me/addemoji/exppwebs_by_fStikBot</code>\n\n"
                "<i>Sticker packs (addstickers) and custom-emoji packs (addemoji) "
                "are both supported.</i></blockquote>",
            )
        role, short = _parse_setpack_args(arg)
        if not short:
            return await _reply(
                e,
                "<blockquote>\u26A0\uFE0F Could not read that link.\n"
                "Use <code>/setpack apps https://t.me/addemoji/YourPack</code></blockquote>",
            )

        stickers.set_pack_name(role, short)
        cache = await stickers.load_pack(bot, short_name=short, force=True, role=role)
        n_docs = len(cache.get("docs") or [])
        n_emoji = len(cache.get("by_emoji") or {})
        kind = "custom emoji" if cache.get("is_emoji") else "stickers"

        if n_docs:
            text = (
                f"<blockquote>{PE_CHECK} <b>Pack connected!</b>\n\n"
                f"{_role_icon(role)} <b>Role:</b> <code>{role}</code>\n"
                f"{PE_GIFT} <b>Pack:</b> <code>{html.escape(short)}</code>\n"
                f"{PE_STAR} <b>{kind.capitalize()}:</b> {n_docs}\n"
                f"{PE_LIGHTNING} <b>Emoji keys:</b> {n_emoji}\n"
                f"{PE_CROWN} <b>Mode:</b> {_mode_label(stickers.get_send_mode())}\n\n"
                "<i>This pack will now be used automatically.</i></blockquote>"
            )
        else:
            text = (
                f"<blockquote>\u26A0\uFE0F <b>Pack saved but could not be loaded.</b>\n\n"
                f"{_role_icon(role)} <b>Role:</b> <code>{role}</code>\n"
                f"{PE_GIFT} <b>Pack:</b> <code>{html.escape(short)}</code>\n\n"
                "Make sure the pack is <b>public</b> and the bot can see it, then "
                f"run <code>/packsync {role}</code>.</blockquote>"
            )
        btns = [[
            style_btn("\U0001F504 Sync now", b"pk_sync", "success", icon=5409320020058584473),
            style_btn("\U0001F4CA Pack status", b"pk_status", "primary", icon=5409320020058584473),
        ]]
        await _reply(e, text, btns)

    @bot.on(events.NewMessage(pattern=r"(?i)^/pack(?:@\w+)?$"))
    async def cmd_pack(e):
        if not _is_admin(e.sender_id):
            return
        await _reply(e, _stats_text(), _stats_buttons())

    @bot.on(events.NewMessage(pattern=r"(?i)^/packsync(?:@\w+)?(?:\s+(\w+))?$"))
    async def cmd_packsync(e):
        if not _is_admin(e.sender_id):
            return
        arg = (e.pattern_match.group(1) or "").strip().lower()
        roles = [arg] if arg in stickers.ROLES else list(stickers.ROLES)
        await _reply(e, "<blockquote>\u23F3 Syncing pack(s)\u2026</blockquote>")
        for role in roles:
            name = stickers.get_pack_name(role)
            if not name:
                continue
            cache = await stickers.load_pack(bot, short_name=name, force=True, role=role)
            logger.info(f"packsync {role}/{name}: {len(cache.get('docs') or [])} docs")
        await _reply(e, _stats_text(), _stats_buttons())

    @bot.on(events.NewMessage(pattern=r"(?i)^/packmode(?:@\w+)?(?:\s+(\w+))?$"))
    async def cmd_packmode(e):
        if not _is_admin(e.sender_id):
            return
        arg = (e.pattern_match.group(1) or "").strip().lower()
        if not arg:
            return await _reply(
                e,
                f"<blockquote>{PE_LIGHTNING} <b>Emoji mode</b>\n\n"
                f"Current: {_mode_label(stickers.get_send_mode())}\n\n"
                "<code>/packmode off</code> \u2014 no emoji\n"
                "<code>/packmode country</code> \u2014 country flags only\n"
                "<code>/packmode all</code> \u2014 country + app emoji</blockquote>",
            )
        if not stickers.set_send_mode(arg):
            return await _reply(
                e, "<blockquote>\u26A0\uFE0F Use <code>off</code>, <code>country</code> or <code>all</code>.</blockquote>"
            )
        await _reply(
            e,
            f"<blockquote>{PE_CHECK} <b>Emoji mode updated</b>\n\n"
            f"Now: {_mode_label(stickers.get_send_mode())}</blockquote>",
        )

    @bot.on(events.NewMessage(pattern=r"(?i)^/packtest(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_packtest(e):
        if not _is_admin(e.sender_id):
            return
        raw = (e.pattern_match.group(1) or "").strip()
        if not raw:
            return await _reply(
                e,
                "<blockquote>Usage: <code>/packtest India</code> or "
                "<code>/packtest WhatsApp apps</code></blockquote>",
            )
        parts = raw.split()
        role = None
        if parts and parts[-1].lower() in stickers.ROLES:
            role = parts[-1].lower()
            name = " ".join(parts[:-1]).strip()
        else:
            name = raw
        if not name:
            return await _reply(e, "<blockquote>\u26A0\uFE0F Send a name to test.</blockquote>")

        for r in ([role] if role else list(stickers.ROLES)):
            await stickers.load_pack(bot, role=r)
        ref = stickers.resolve(name, role=role)
        if not ref:
            return await _reply(
                e,
                f"<blockquote>\U0001F50D <b>{html.escape(name)}</b> \u2014 no matching emoji found.\n\n"
                "Reply to an emoji/sticker with <code>/mapsticker "
                f"{html.escape(name)}</code> to pin one manually.</blockquote>",
            )
        try:
            await stickers._send_ref(bot, e.chat_id, ref, reply_to=e.id)
        except Exception as exc:
            logger.warning(f"packtest send failed: {exc}")
        await _reply(
            e,
            f"<blockquote>{PE_CHECK} <b>{html.escape(name)}</b> \u2192 sent above.</blockquote>",
        )

    @bot.on(events.NewMessage(pattern=r"(?i)^/mapsticker(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_mapsticker(e):
        if not _is_admin(e.sender_id):
            return
        name = (e.pattern_match.group(1) or "").strip()
        if not name:
            return await _reply(
                e,
                "<blockquote>Reply to an emoji/sticker with:\n"
                "<code>/mapsticker India</code></blockquote>",
            )
        reply = await e.get_reply_message()
        doc = None
        if reply and getattr(reply, "media", None):
            doc = getattr(reply.media, "document", None)
        if doc is None:
            return await _reply(
                e, "<blockquote>\u26A0\uFE0F Reply to a <b>sticker or custom emoji</b> message with this command.</blockquote>"
            )
        ref = stickers.ref_from_document(doc)
        stickers.map_name(name, ref)
        await _reply(
            e,
            f"<blockquote>{PE_CHECK} Pinned emoji for <b>{html.escape(name)}</b>.\n"
            "<i>This override always wins over auto-matching.</i></blockquote>",
        )

    @bot.on(events.NewMessage(pattern=r"(?i)^/unmapsticker(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_unmapsticker(e):
        if not _is_admin(e.sender_id):
            return
        name = (e.pattern_match.group(1) or "").strip()
        if not name:
            return await _reply(e, "<blockquote>Usage: <code>/unmapsticker India</code></blockquote>")
        removed = stickers.unmap_name(name)
        if removed:
            await _reply(
                e, f"<blockquote>{PE_CHECK} Removed override for <b>{html.escape(name)}</b>.</blockquote>"
            )
        else:
            await _reply(
                e, f"<blockquote>\u2139\uFE0F No override existed for <b>{html.escape(name)}</b>.</blockquote>"
            )

    @bot.on(events.NewMessage(pattern=r"(?i)^/packmap(?:@\w+)?$"))
    async def cmd_packmap(e):
        if not _is_admin(e.sender_id):
            return
        items = stickers.list_map(limit=80)
        if not items:
            return await _reply(
                e,
                "<blockquote>\U0001F4CB <b>No manual overrides yet.</b>\n\n"
                "Reply to an emoji/sticker with <code>/mapsticker India</code> to add one.</blockquote>",
            )
        lines = "\n".join(f"\u2022 <code>{html.escape(k)}</code>" for k, _ in items)
        await _reply(
            e,
            f"<blockquote>{PE_TAG} <b>Manual emoji overrides</b> ({len(items)})\n\n"
            f"{lines}</blockquote>",
        )

    # ------------------------------------------------------------------
    # inline buttons on the /pack card
    # ------------------------------------------------------------------
    @bot.on(events.CallbackQuery(pattern=r"^pk_status$"))
    async def cb_status(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        try:
            await e.edit(_stats_text(), buttons=_stats_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^pk_sync$"))
    async def cb_sync(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        await e.answer("Syncing\u2026")
        for role in stickers.ROLES:
            name = stickers.get_pack_name(role)
            if name:
                await stickers.load_pack(bot, short_name=name, force=True, role=role)
        try:
            await e.edit(_stats_text(), buttons=_stats_buttons())
        except Exception:
            pass


def _role_line(st):
    icon = _role_icon(st["role"])
    kind = "\u2728" if st["is_emoji"] else "\U0001F3F7\uFE0F"
    if not st["short"]:
        return f"{icon} <b>{st['label']}:</b> <i>not set</i>"
    age = "just now" if st["age"] is None or st["age"] < 60 else f"{st['age'] // 60} min ago"
    return (
        f"{icon} <b>{st['label']}:</b> <code>{html.escape(st['short'])}</code> "
        f"{kind} {st['stickers']} \u00b7 {st['emoji_keys']} keys \u00b7 {age}"
    )


def _stats_text():
    stats = stickers.all_stats()
    lines = "\n".join(_role_line(stats[r]) for r in stickers.ROLES)
    return (
        f"<blockquote>{PE_GIFT} <b>Premium Emoji Packs</b>\n\n"
        f"{lines}\n\n"
        f"{PE_TAG} <b>Manual overrides:</b> {stats['flags']['manual']}\n"
        f"{PE_CROWN} <b>Mode:</b> {_mode_label(stats['flags']['mode'])}</blockquote>\n"
        "<blockquote><i>Connect packs with "
        "<code>/setpack flags|apps|misc &lt;link&gt;</code></i></blockquote>"
    )


def _stats_buttons():
    return [
        [style_btn("\U0001F504 Sync all packs", b"pk_sync", "success", icon=5409320020058584473)],
        [style_btn("\U0001F4CA Refresh", b"pk_status", "primary", icon=5409320020058584473)],
    ]
