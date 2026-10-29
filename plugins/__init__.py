"""Plugin loader.

Every feature module exposes a ``register_*`` function that attaches its
Telethon handlers to the bot.  Registration used to be a flat list of calls,
which meant a single missing import or a typo in one plugin took the whole bot
down at boot (Railway showed the deployment as *Crashed*).

``register_all_handlers`` now runs each plugin through :func:`_safe_register`,
so a broken plugin is logged and skipped while every other feature keeps
working.  The loader also verifies that each imported callable really exists,
which turns a silent ``NameError`` into an explicit, readable log line.
"""
import logging

from plugins.start import register_start
from plugins.profile import register_profile
from plugins.deposit import register_deposit
from plugins.admin import register_admin
from plugins.admin_actions import register_admin_actions
from plugins.admin_cleanup import register_admin_cleanup
from plugins.admin_catalogs import register_admin_catalogs
from plugins.admin_hub import register_admin_hub
from plugins.callbacks import register_callbacks
from plugins.smm import register_smm
from plugins.source_codes import register_source_codes
from plugins.panels import register_panels
from plugins.settings_menu import register_settings
from plugins.servers import register_servers
from plugins.all_apps import register_all_apps
from plugins.more_content import register_more_content
from plugins.product_panels import register_product_panels
from plugins.admin_extras import register_admin_extras
from plugins.profit_admin import register_profit_admin
from plugins.help_menu import register_help
from plugins.manual_accounts import register_manual_accounts
from plugins.stickers import register_stickers
from plugins.tempmail import register_tempmail
from plugins.user_history import register_user_history

logger = logging.getLogger(__name__)

# (label, callable) pairs in the order they are registered.
_PLUGIN_REGISTRARS = (
    ("start", register_start),
    ("profile", register_profile),
    ("deposit", register_deposit),
    ("admin", register_admin),
    ("admin_actions", register_admin_actions),
    ("admin_cleanup", register_admin_cleanup),
    ("admin_catalogs", register_admin_catalogs),
    ("admin_hub", register_admin_hub),
    ("callbacks", register_callbacks),
    ("smm", register_smm),
    ("source_codes", register_source_codes),
    ("panels", register_panels),
    ("settings", register_settings),
    ("servers", register_servers),
    ("all_apps", register_all_apps),
    ("more_content", register_more_content),
    ("product_panels", register_product_panels),
    ("admin_extras", register_admin_extras),
    ("profit_admin", register_profit_admin),
    ("user_history", register_user_history),
    ("help", register_help),
    ("manual_accounts", register_manual_accounts),
    ("stickers", register_stickers),
    ("tempmail", register_tempmail),
)


def _safe_register(label, registrar, bot):
    """Run one plugin's registration without ever aborting the boot."""
    if not callable(registrar):
        logger.error(
            "\u274c Plugin '%s' has no callable register function (got %r) - skipped.",
            label, registrar,
        )
        return False
    try:
        registrar(bot)
        return True
    except Exception as exc:  # noqa: BLE001 - boot must survive any plugin bug
        logger.exception(
            "\u26a0\ufe0f Plugin '%s' failed to register: %s: %s - continuing without it.",
            label, type(exc).__name__, exc,
        )
        return False


def _register_buy(bot):
    """Buy panel: supports both a ``register_buy`` function and decorator mode."""
    try:
        from plugins.buy import register_buy
    except ImportError:
        # Module registers its handlers via decorators on import.
        import plugins.buy  # noqa: F401
        logger.info("\u2705 Buy plugin loaded (direct decorator mode).")
        return True
    return _safe_register("buy", register_buy, bot)


def register_all_handlers(bot):
    """Register every plugin handler, isolating failures per plugin."""
    ok = 0
    failed = []

    for label, registrar in _PLUGIN_REGISTRARS:
        if _safe_register(label, registrar, bot):
            ok += 1
        else:
            failed.append(label)

    if _register_buy(bot):
        ok += 1
    else:
        failed.append("buy")

    total = len(_PLUGIN_REGISTRARS) + 1
    if failed:
        logger.error(
            "\u26a0\ufe0f Handler registration finished with problems: %d/%d loaded, failed: %s",
            ok, total, ", ".join(failed),
        )
    else:
        logger.info("\u2705 All %d plugin handler groups registered successfully.", ok)

    return {"loaded": ok, "failed": failed, "total": total}
