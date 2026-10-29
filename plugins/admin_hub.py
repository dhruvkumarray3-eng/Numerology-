"""Admin \u201cAdvanced Tools\u201d hub.

Several powerful admin features used to be reachable **only** by typing a
command (``/panelstats``, ``/panelsales``, ``/panelbalance``, ``/mongostatus``,
``/smmservers``, ``/grant``, ``/myhistory``, ``/basictg``, ``/pack`` ...).

The owner asked for *every* feature to live inside the Admin Panel, so this
module puts one button in front of each of them.  Nothing here re-implements
business logic \u2013 every action delegates to the already-tested implementation
in ``plugins.admin_extras`` / ``plugins.manual_accounts`` / ``plugins.stickers``.

Callback prefix is ``hub_`` on purpose: ``plugins.admin_actions`` owns the
catch-all ``^adm_`` pattern, and unknown ``adm_*`` payloads would fall through
into its ``bot.conversation()`` block.
"""
from __future__ import annotations

import html

from telethon import events

from config import bot, is_super_admin
from database import cur, db, ensure_user, has_perm, is_admin
from utils.keyboards import style_btn

BACK_ICON = 6129812419028982717
HUB_HOME = "hub_open"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _allowed(uid, perm=None):
    if not is_admin(uid):
        return False
    if perm is None:
        return True
    return is_super_admin(uid) or has_perm(uid, perm)


def _back_row(target=HUB_HOME):
    return [style_btn("\u2b05\ufe0f Back", target, "danger", icon=BACK_ICON)]


def _hub_text(uid):
    return (
        "<blockquote expandable>\U0001F6E0 <b>\U0001d400\U0001d41d\U0001d42f\U0001d41a\U0001d427\U0001d41c\U0001d41e\U0001d41d "
        "\U0001d413\U0001d428\U0001d428\U0001d425\U0001d42c</b>\n\n"
        "\U0001F4CA <b>Panel Analytics</b> \u2014 revenue, cost, profit per panel\n"
        "\U0001F9FE <b>Panel Sales</b> \u2014 last orders with status\n"
        "\U0001F4BC <b>Panel Balance</b> \u2014 live OTP provider wallet\n"
        "\U0001F5C4 <b>DB Status</b> \u2014 SQLite + MongoDB storage health\n"
        "\U0001F5A5 <b>SMM Servers</b> \u2014 every server switch in one place\n"
        "\U0001F381 <b>Grant Balance</b> \u2014 credit a user instantly\n"
        "\U0001F9D1\u200D\U0001F4BB <b>Basic TG Accounts</b> \u2014 manual account catalog\n"
        "\U0001F3A8 <b>Sticker Packs</b> \u2014 pack status, sync and emoji map\n"
        "\U0001F4DC <b>My History</b> \u2014 your own admin activity\n\n"
        "<i>Every one of these is also available as a slash command.</i></blockquote>"
    )


def _hub_buttons(uid):
    rows = [
        [style_btn("\U0001F4CA Panel Analytics", "hub_do|panelstats", "success", icon="money"),
         style_btn("\U0001F9FE Panel Sales", "hub_do|panelsales", "primary", icon="panel")],
        [style_btn("\U0001F4BC Panel Balance", "hub_do|panelbalance", "success", icon="money"),
         style_btn("\U0001F5C4 DB Status", "hub_do|mongostatus", "primary", icon="server")],
        [style_btn("\U0001F5A5 SMM Servers", "hub_do|smmservers", "primary", icon="server"),
         style_btn("\U0001F381 Grant Balance", "hub_do|grant", "success", icon="money")],
        [style_btn("\U0001F9D1\u200D\U0001F4BB Basic TG Accounts", "hub_do|basictg", "primary", icon="telegram"),
         style_btn("\U0001F3A8 Sticker Packs", "hub_do|packs", "success", icon="crown")],
        [style_btn("\U0001F4DC My History", "hub_do|myhistory", "primary", icon="check")],
        [style_btn("\u2b05\ufe0f Back to Admin", "adm_adminmain", "danger", icon=BACK_ICON)],
    ]
    return rows


class _Shim:
    """Adapts a CallbackQuery event to the ``reply()``-style API the
    command handlers expect, while *editing* the current message so the
    admin never loses the navigation buttons."""

    def __init__(self, event, back=HUB_HOME):
        self._event = event
        self.sender_id = event.sender_id
        self.chat_id = event.chat_id
        self.id = getattr(event, "id", None)
        self.client = getattr(event, "client", None)
        self.raw_text = ""
        self.text = ""
        self.pattern_match = None
        self._back = back

    async def reply(self, text, buttons=None, **kwargs):
        btns = buttons if buttons is not None else _back_row(self._back)
        try:
            return await self._event.edit(text, buttons=btns, **kwargs)
        except Exception:
            try:
                return await self._event.respond(text, buttons=btns, **kwargs)
            except Exception:
                return None

    async def respond(self, text, buttons=None, **kwargs):
        return await self.reply(text, buttons=buttons, **kwargs)

    async def edit(self, text, buttons=None, **kwargs):
        return await self.reply(text, buttons=buttons, **kwargs)

    async def answer(self, *args, **kwargs):
        try:
            return await self._event.answer(*args, **kwargs)
        except Exception:
            return None

    async def get_reply_message(self):
        return None


async def show_hub(event):
    uid = event.sender_id
    if not _allowed(uid):
        return
    try:
        await event.edit(_hub_text(uid), buttons=_hub_buttons(uid))
    except Exception:
        try:
            await event.respond(_hub_text(uid), buttons=_hub_buttons(uid))
        except Exception:
            pass


async def _run_action(event, action):
    """Delegate to the real implementation behind each slash command."""
    from plugins import admin_extras as ax

    shim = _Shim(event)

    if action == "panelstats":
        return await ax.cmd_panelstats(shim)
    if action == "panelsales":
        return await ax.cmd_panelsales(shim, "")
    if action == "panelbalance":
        return await ax.cmd_panelbalance(shim)
    if action == "mongostatus":
        return await ax.cmd_mongostatus(shim)
    if action == "smmservers":
        return await ax.cmd_smmservers(shim)
    if action == "myhistory":
        return await ax.cmd_myhistory(shim)
    if action == "basictg":
        from plugins import manual_accounts as ma
        return await ma.show_home(shim)
    if action == "packs":
        return await _render_packs(event)
    return None


async def _render_packs(event):
    """Sticker-pack screen, reachable from the hub (was /pack only)."""
    from plugins import stickers as st
    from utils import stickers as stlib

    btns = list(st._stats_buttons())
    mode = stlib.get_send_mode()
    btns.append([style_btn(f"\U0001F501 Send Mode: {st._mode_label(mode)}",
                           "hub_pkmode", "primary", icon="settings")])
    btns.append(_back_row())
    try:
        await event.edit(st._stats_text(), buttons=btns)
    except Exception:
        pass
    return None


async def _grant_wizard(event):
    """Credit a user's balance without typing /grant."""
    uid = event.sender_id
    if not _allowed(uid, "p_bal"):
        return await event.answer("No permission.", alert=True)

    await event.answer()
    chat = event.chat_id
    try:
        await event.edit(
            "<blockquote>\U0001F381 <b>Grant Balance</b>\n\n"
            "Send the target <b>user ID</b> and the <b>amount</b> in one line.\n"
            "Example: <code>123456789 250</code>\n\n"
            "<i>Type /cancel to abort.</i></blockquote>",
            buttons=_back_row(),
        )
    except Exception:
        pass

    async with bot.conversation(chat, timeout=300) as conv:
        try:
            resp = await conv.get_response()
        except Exception:
            return None
        text = (resp.raw_text or "").strip()
        if text.lower() in ("/cancel", "cancel"):
            return await conv.send_message("\u274c Cancelled.")
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit():
            return await conv.send_message(
                "\u274c Usage: <code>123456789 250</code>", parse_mode="html")
        target = int(parts[0])
        try:
            amount = float(parts[1])
        except ValueError:
            return await conv.send_message("\u274c Amount must be a number.")
        if amount <= 0:
            return await conv.send_message("\u274c Amount must be greater than zero.")
        ensure_user(target)
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, target))
        db.commit()
        try:
            from utils import mongo_store
            await mongo_store.log_event(uid, "admin_grant", target=target, amount=amount)
        except Exception:
            pass
        row = cur.execute("SELECT balance FROM users WHERE user_id=?", (target,)).fetchone()
        new_bal = row[0] if row else amount
        await conv.send_message(
            f"\u2705 Credited <b>\u20b9{amount:,.2f}</b> to <code>{target}</code>.\n"
            f"New balance: <b>\u20b9{new_bal:,.2f}</b>",
            parse_mode="html",
            buttons=_back_row(),
        )
    return None


def register_admin_hub(bot):
    @bot.on(events.CallbackQuery(pattern=r"^hub_open$"))
    async def cb_hub_open(e):
        if not _allowed(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        await show_hub(e)

    @bot.on(events.CallbackQuery(pattern=r"^hub_pkmode$"))
    async def cb_hub_pkmode(e):
        if not _allowed(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        from utils import stickers as stlib

        order = ("off", "country", "all")
        cur_mode = stlib.get_send_mode()
        nxt = order[(order.index(cur_mode) + 1) % len(order)] if cur_mode in order else "country"
        stlib.set_send_mode(nxt)
        await e.answer(f"Send mode: {nxt}")
        await _render_packs(e)

    @bot.on(events.CallbackQuery(pattern=r"^hub_do\|(\w+)$"))
    async def cb_hub_do(e):
        if not _allowed(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        action = e.pattern_match.group(1)
        if action == "grant":
            return await _grant_wizard(e)
        await e.answer()
        try:
            await _run_action(e, action)
        except Exception as exc:  # never leave the admin on a dead button
            try:
                await e.edit(
                    f"<blockquote>\u26a0\ufe0f <b>{html.escape(action)}</b> failed:\n"
                    f"<code>{html.escape(str(exc))}</code></blockquote>",
                    buttons=_back_row(),
                )
            except Exception:
                pass
