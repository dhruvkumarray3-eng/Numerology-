"""Premium sticker-pack admin surface.

The owner pastes a Telegram sticker-pack link and the bot learns the whole
pack, then automatically sends the *right* premium sticker whenever a country
or an app is shown to a user.

Commands (admins only):
    /setpack <link>        -> learn a pack from https://t.me/addstickers/XXX
    /pack                  -> pack status card (count, keys, mode, overrides)
    /packsync              -> force re-download the pack (picks up new stickers)
    /packmode off|country|all
                           -> off     : no stickers
                              country : country flag stickers only  (default)
                              all     : country + app stickers
    /packtest <name>       -> preview which sticker a name resolves to
    /mapsticker <name>     -> reply to a sticker to pin it for <name>
    /unmapsticker <name>   -> drop a manual override
    /packmap               -> list manual overrides

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
        "off": "🚫 Off",
        "country": "🌍 Country only",
        "all": "🌍 Country + 📱 Apps",
    }.get(mode, mode)


async def _reply(event, text, buttons=None):
    try:
        await event.respond(text, buttons=buttons, parse_mode="html")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"stickers reply failed: {exc}")


def register_stickers(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/setpack(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_setpack(e):
        if not _is_admin(e.sender_id):
            return
        arg = (e.pattern_match.group(1) or "").strip()
        if not arg:
            return await _reply(
                e,
                f"<blockquote>{PE_TAG} <b>Set Premium Sticker Pack</b>\n\n"
                "Send the pack link like this:\n"
                "<code>/setpack https://t.me/addstickers/YourPack</code>\n\n"
                "<i>The bot will learn every sticker and match them to country "
                "flags and app icons automatically.</i></blockquote>",
            )
        short = stickers.parse_pack_link(arg)
        if not short:
            return await _reply(
                e,
                "<blockquote>⚠️ Could not read that link.\n"
                "Use <code>/setpack https://t.me/addstickers/YourPack</code></blockquote>",
            )

        stickers.set_pack_name(short)
        cache = await stickers.load_pack(bot, short_name=short, force=True)
        n_docs = len(cache.get("docs") or [])
        n_emoji = len(cache.get("by_emoji") or {})

        if n_docs:
            text = (
                f"<blockquote>{PE_CHECK} <b>Pack connected!</b>\n\n"
                f"{PE_GIFT} <b>Pack:</b> <code>{html.escape(short)}</code>\n"
                f"{PE_STAR} <b>Stickers:</b> {n_docs}\n"
                f"{PE_LIGHTNING} <b>Emoji keys:</b> {n_emoji}\n"
                f"{PE_CROWN} <b>Mode:</b> {_mode_label(stickers.get_send_mode())}\n\n"
                "<i>Country flags and app stickers will now be sent automatically.</i>"
                "</blockquote>"
            )
        else:
            text = (
                f"<blockquote>⚠️ <b>Pack saved but could not be loaded.</b>\n\n"
                f"{PE_GIFT} <b>Pack:</b> <code>{html.escape(short)}</code>\n\n"
                "Make sure the pack is <b>public</b> and the bot can see it, then "
                "run <code>/packsync</code>.</blockquote>"
            )
        btns = [[
            style_btn("🔄 Sync now", b"pk_sync", "success", icon=5409320020058584473),
            style_btn("📊 Pack status", b"pk_status", "primary", icon=5409320020058584473),
        ]]
        await _reply(e, text, btns)

    @bot.on(events.NewMessage(pattern=r"(?i)^/pack(?:@\w+)?$"))
    async def cmd_pack(e):
        if not _is_admin(e.sender_id):
            return
        await _reply(e, _stats_text(), _stats_buttons())

    @bot.on(events.NewMessage(pattern=r"(?i)^/packsync(?:@\w+)?$"))
    async def cmd_packsync(e):
        if not _is_admin(e.sender_id):
            return
        name = stickers.get_pack_name()
        if not name:
            return await _reply(
                e, "<blockquote>⚠️ No pack set yet. Use <code>/setpack &lt;link&gt;</code></blockquote>"
            )
        await _reply(e, "<blockquote>⏳ Syncing sticker pack…</blockquote>")
        cache = await stickers.load_pack(bot, short_name=name, force=True)
        await _reply(e, _stats_text(), _stats_buttons())
        logger.info(f"packsync {name}: {len(cache.get('docs') or [])} stickers")

    @bot.on(events.NewMessage(pattern=r"(?i)^/packmode(?:@\w+)?(?:\s+(\w+))?$"))
    async def cmd_packmode(e):
        if not _is_admin(e.sender_id):
            return
        arg = (e.pattern_match.group(1) or "").strip().lower()
        if not arg:
            return await _reply(
                e,
                f"<blockquote>{PE_LIGHTNING} <b>Sticker mode</b>\n\n"
                f"Current: {_mode_label(stickers.get_send_mode())}\n\n"
                "<code>/packmode off</code> — no stickers\n"
                "<code>/packmode country</code> — country flags only\n"
                "<code>/packmode all</code> — country + app stickers</blockquote>",
            )
        if not stickers.set_send_mode(arg):
            return await _reply(
                e, "<blockquote>⚠️ Use <code>off</code>, <code>country</code> or <code>all</code>.</blockquote>"
            )
        await _reply(
            e,
            f"<blockquote>{PE_CHECK} <b>Sticker mode updated</b>\n\n"
            f"Now: {_mode_label(stickers.get_send_mode())}</blockquote>",
        )

    @bot.on(events.NewMessage(pattern=r"(?i)^/packtest(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_packtest(e):
        if not _is_admin(e.sender_id):
            return
        name = (e.pattern_match.group(1) or "").strip()
        if not name:
            return await _reply(
                e, "<blockquote>Usage: <code>/packtest India</code> or <code>/packtest WhatsApp</code></blockquote>"
            )
        if not stickers.get_pack_name():
            return await _reply(e, "<blockquote>⚠️ No pack set. Use <code>/setpack &lt;link&gt;</code></blockquote>")
        await stickers.load_pack(bot)
        ref = stickers.resolve(name)
        if not ref:
            return await _reply(
                e,
                f"<blockquote>🔍 <b>{html.escape(name)}</b> — no matching sticker found.\n\n"
                "Reply to a sticker with <code>/mapsticker "
                f"{html.escape(name)}</code> to pin one manually.</blockquote>",
            )
        try:
            await bot.send_file(e.chat_id, stickers._ref_to_input(ref), reply_to=e.id)
        except Exception as exc:
            logger.warning(f"packtest send failed: {exc}")
        await _reply(
            e,
            f"<blockquote>{PE_CHECK} <b>{html.escape(name)}</b> → sticker sent above.</blockquote>",
        )

    @bot.on(events.NewMessage(pattern=r"(?i)^/mapsticker(?:@\w+)?(?:\s+(.+))?$"))
    async def cmd_mapsticker(e):
        if not _is_admin(e.sender_id):
            return
        name = (e.pattern_match.group(1) or "").strip()
        if not name:
            return await _reply(
                e,
                "<blockquote>Reply to a sticker with:\n"
                "<code>/mapsticker India</code></blockquote>",
            )
        reply = await e.get_reply_message()
        doc = None
        if reply and getattr(reply, "media", None):
            doc = getattr(reply.media, "document", None)
        if doc is None:
            return await _reply(
                e, "<blockquote>⚠️ Reply to a <b>sticker</b> message with this command.</blockquote>"
            )
        ref = stickers.ref_from_document(doc)
        stickers.map_name(name, ref)
        await _reply(
            e,
            f"<blockquote>{PE_CHECK} Pinned sticker for <b>{html.escape(name)}</b>.\n"
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
                e, f"<blockquote>ℹ️ No override existed for <b>{html.escape(name)}</b>.</blockquote>"
            )

    @bot.on(events.NewMessage(pattern=r"(?i)^/packmap(?:@\w+)?$"))
    async def cmd_packmap(e):
        if not _is_admin(e.sender_id):
            return
        items = stickers.list_map(limit=80)
        if not items:
            return await _reply(
                e,
                "<blockquote>📋 <b>No manual overrides yet.</b>\n\n"
                "Reply to a sticker with <code>/mapsticker India</code> to add one.</blockquote>",
            )
        lines = "\n".join(f"• <code>{html.escape(k)}</code>" for k, _ in items)
        await _reply(
            e,
            f"<blockquote>{PE_TAG} <b>Manual sticker overrides</b> ({len(items)})\n\n"
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
        name = stickers.get_pack_name()
        if not name:
            return await e.answer("No pack set. Use /setpack <link>.", alert=True)
        await e.answer("Syncing…")
        await stickers.load_pack(bot, short_name=name, force=True)
        try:
            await e.edit(_stats_text(), buttons=_stats_buttons())
        except Exception:
            pass


def _stats_text():
    st = stickers.pack_stats()
    if not st["short"]:
        return (
            f"<blockquote>{PE_GIFT} <b>Premium Stickers</b>\n\n"
            "No pack connected yet.\n\n"
            "Send <code>/setpack https://t.me/addstickers/YourPack</code> "
            "to add premium country &amp; app stickers.</blockquote>"
        )
    age = "just now" if st["age"] is None or st["age"] < 60 else f"{st['age'] // 60} min ago"
    return (
        f"<blockquote>{PE_GIFT} <b>Premium Sticker Pack</b>\n\n"
        f"{PE_ID} <b>Pack:</b> <code>{html.escape(st['short'])}</code>\n"
        f"{PE_STAR} <b>Stickers:</b> {st['stickers']}\n"
        f"{PE_LIGHTNING} <b>Emoji keys:</b> {st['emoji_keys']} · "
        f"<b>Text keys:</b> {st['text_keys']}\n"
        f"{PE_TAG} <b>Manual overrides:</b> {st['manual']}\n"
        f"{PE_CROWN} <b>Mode:</b> {_mode_label(st['mode'])}\n"
        f"🕒 <b>Synced:</b> {age}</blockquote>"
    )


def _stats_buttons():
    return [
        [style_btn("🔄 Sync pack", b"pk_sync", "success", icon=5409320020058584473)],
        [style_btn("📊 Refresh", b"pk_status", "primary", icon=5409320020058584473)],
    ]
