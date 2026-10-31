"""High-priority router for the bottom reply keyboard.

Why this module exists
----------------------
Reply-keyboard labels are rendered with mathematical-bold / small-capital
Unicode glyphs (``📊 𝐒ᴛᴏᴄᴋ``, ``👤 𝐏ʀᴏꜰɪʟᴇ``).  Individual plugins each had
their own ``NewMessage(pattern=...)`` handler for one of those labels, and the
regexes were written by hand against the *wrong* Unicode block (``𝕊`` vs
``𝐒``, ``ℙ`` vs ``𝐏``).  When a regex missed, the tap fell through to the
catch-all country-search handler in ``plugins/buy.py`` and the bot answered
``No country found matching '📊 𝐒ᴛᴏᴄᴋ'`` — the Stock button looked dead.

Even after fixing the glyphs, priority still depended on plugin import order:
``plugins.buy`` registers its handlers at import time (direct decorator mode),
so if it is imported before ``register_callbacks`` runs, its catch-all wins and
the button breaks again.

This router is registered **first** (``main.py`` calls it before
``register_all_handlers``), matches every keyboard label through the canonical
folded key, dispatches to the right screen, and always raises
``StopPropagation`` so no catch-all can ever hijack a button tap.

It is also the single place to add a new keyboard shortcut: add the label to
``utils.keyboards._MENU_LABEL_KEYS`` and a branch here.
"""
import logging

from telethon import events

from utils.keyboards import menu_label_key

logger = logging.getLogger(__name__)


def _clear_pending(uid):
    """Drop half-finished input states before showing a fresh menu screen."""
    try:
        from plugins.buy import search_state, user_states
        search_state.pop(uid, None)
        if user_states.get(uid) in (None, "AWAITING_COUNTRY"):
            user_states.pop(uid, None)
    except Exception:
        pass
    for mod_name, attr in (
        ("plugins.more_content", "more_state"),
        ("plugins.all_apps", "app_state"),
    ):
        try:
            mod = __import__(mod_name, fromlist=[attr])
            state = getattr(mod, attr, None)
            if isinstance(state, dict):
                state.pop(uid, None)
        except Exception:
            pass


async def _dispatch(bot, event, key):
    """Send the screen that belongs to ``key``.  Returns True when handled."""
    uid = event.sender_id

    if key == "stock":
        from plugins.callbacks import send_stock_page
        await send_stock_page(event, 1)
        return True

    if key == "profile":
        from plugins.profile import profile_handler
        await profile_handler(bot, event)
        return True

    if key == "my_stats":
        from plugins.profile import stats_handler
        await stats_handler(bot, event)
        return True

    if key == "my_orders":
        from plugins.callbacks import send_my_orders
        await send_my_orders(event)
        return True

    if key == "balance":
        from plugins.callbacks import send_balance
        await send_balance(event)
        return True

    if key == "refer":
        from plugins.callbacks import show_refer_menu
        await show_refer_menu(bot, event)
        return True

    if key == "support":
        from plugins.callbacks import send_support
        await send_support(event)
        return True

    if key in ("deposit", "recharge"):
        from plugins.deposit import deposit_menu
        await deposit_menu(event)
        return True

    if key == "buy_account":
        from plugins.buy import show_buy_menu
        await show_buy_menu(event)
        return True

    if key == "start":
        from plugins.start import send_main_menu
        await send_main_menu(bot, None, uid)
        return True

    if key == "close":
        from telethon.tl.custom.button import Button
        from database import set_menu_installed
        try:
            from plugins.start import _menu_installed
            _menu_installed.discard(uid)
        except Exception:
            pass
        set_menu_installed(uid, 0)
        await event.respond(
            "\U0001f53d <i>Keyboard closed. Tap /menu or /start anytime to reopen.</i>",
            buttons=Button.clear(),
        )
        return True

    if key == "help":
        from plugins.help_menu import show_help
        await show_help(event)
        return True

    if key == "admin_panel":
        from plugins.admin import admin_panel_handler
        await admin_panel_handler(event)
        return True

    if key == "settings":
        from plugins.settings_menu import show_settings
        await show_settings(event, uid)
        return True

    if key == "servers":
        from plugins.servers import show_servers
        await show_servers(bot, event)
        return True

    if key == "tempmail":
        from plugins.tempmail import show_home
        await show_home(event)
        return True

    return False


def register_menu_router(bot):
    """Register the single, highest-priority reply-keyboard router."""

    @bot.on(events.NewMessage(
        func=lambda e: e.is_private and not e.out
        and menu_label_key(e.raw_text) is not None
    ))
    async def menu_label_router(event):
        key = menu_label_key(event.raw_text)
        uid = event.sender_id
        _clear_pending(uid)
        logger.info("Menu route: %r -> %s", event.raw_text, key)

        # The keyboard lives on the user's phone, so a stale layout keeps
        # sending old glyphs until we replace it.  Refresh it on the very first
        # tap instead of waiting for /start, so the fix reaches users who never
        # reopen the bot explicitly.
        try:
            from database import get_menu_version
            from utils.keyboards import MENU_VERSION
            if get_menu_version(uid) < MENU_VERSION:
                from plugins.start import install_persistent_menu
                await install_persistent_menu(bot, event, uid, force=True)
                logger.info("Refreshed reply keyboard for %s to v%s", uid, MENU_VERSION)
        except Exception as exc:  # noqa: BLE001 - never block the screen
            logger.debug("Keyboard refresh skipped for %s: %s", uid, exc)
        try:
            handled = await _dispatch(bot, event, key)
        except events.StopPropagation:
            raise
        except Exception as exc:  # noqa: BLE001 - a button must never look dead
            logger.error("Menu route %s failed: %s", key, exc, exc_info=True)
            try:
                await event.respond(
                    f"\u26a0\ufe0f <b>{key.replace('_', ' ').title()}</b> is "
                    f"temporarily unavailable.\n<code>{type(exc).__name__}</code> "
                    f"\u2014 please try again in a moment."
                )
            except Exception:
                pass
            raise events.StopPropagation
        if not handled:
            logger.warning("Menu route %s has no screen wired up", key)
        raise events.StopPropagation

    return bot


def self_test():
    """Verify every keyboard label maps to a canonical key.

    Called at boot so the log proves the new routing build is actually live:
    ``✅ Menu routing self-test: 12/12 labels mapped``.
    """
    from utils.keyboards import get_persistent_menu
    try:
        rows = get_persistent_menu(1)
    except Exception as exc:  # noqa: BLE001
        return 0, 0, [f"keyboard build failed: {exc}"]
    missing = []
    total = 0
    for row in rows:
        for btn in row:
            label = getattr(getattr(btn, "button", None), "text", None)
            if not label:
                continue
            total += 1
            if menu_label_key(label) is None:
                missing.append(label)
    return total - len(missing), total, missing
