"""Numbott entrypoint — crash-proof supervisor.

The bot must NEVER take the whole container down.  Historically a single
transient failure (a dropped MTProto connection, a `CancelledError` raised by
asyncio, a stale/corrupt session file, a locked SQLite database) escaped
`main()` and killed the process, which the host showed as
"The app crashed on an unhandled error".

Three layers of protection now exist:

1. ``bot.start()`` retries with exponential backoff instead of re-raising.
2. The reconnect loop catches ``BaseException`` (``asyncio.CancelledError``
   inherits from ``BaseException``, not ``Exception`` — that was the original
   crash), so a cancelled task can no longer kill the process.
3. ``_supervise()`` wraps ``asyncio.run(main())`` in a forever loop, so even
   an unforeseen error only causes a short pause and a restart.

Only a real ``SIGINT``/``SIGTERM`` (or Ctrl+C) stops the bot.
"""
import asyncio
import logging
import os
import sys
import time

from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID, bot

# Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Build marker printed on every boot.  Bump this whenever a fix is pushed so
# the hosting console immediately shows whether the container is running the
# latest code.  If the console still prints an older tag, the container has
# not pulled the new files yet.
BUILD_TAG = "2026-10-30-imap-oauth-ready-v20"

os.makedirs("sessions", exist_ok=True)

# Plugins, Health Server & Utilities
from plugins import register_all_handlers
from utils.health import start_health_server
from utils.helpers import set_bot_instance
from database import apply_official_links_migration

# How long to wait between restart attempts (seconds, capped).
_RESTART_DELAY = 5
_MAX_RESTART_DELAY = 60


def validate_runtime_config() -> bool:
    """Check required environment variables before booting.

    Returns ``True`` when everything needed is present.  A missing variable is
    reported as one clear, readable line instead of a raw traceback.
    """
    missing = []
    if API_ID <= 0:
        missing.append("API_ID")
    if not str(API_HASH or "").strip():
        missing.append("API_HASH")
    if not str(BOT_TOKEN or "").strip():
        missing.append("BOT_TOKEN")
    if ADMIN_ID <= 0:
        missing.append("ADMIN_ID")

    if missing:
        logger.critical(
            "\u274c Missing required environment variable(s): %s. "
            "Add them in your host's Variables/Environment tab "
            "(copy .env.sample for the full list).",
            ", ".join(missing),
        )
        return False
    return True


def _reset_broken_session() -> None:
    """Delete a corrupt/unreadable Telethon session file.

    A half-written or permission-broken ``*.session`` SQLite file makes
    Telethon raise ``sqlite3.DatabaseError`` on every connect attempt.  Since
    the bot logs in with ``bot_token`` every time, throwing the file away is
    always safe.
    """
    for name in ("bot_session.session", "bot_session.session-journal"):
        try:
            if os.path.exists(name):
                os.remove(name)
                logger.warning("\u267b\ufe0f Removed unusable session file: %s", name)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", name, exc)


async def _connect_with_retry() -> bool:
    """Log in to Telegram, retrying forever instead of crashing.

    A wrong token / blocked network is retried with a capped backoff so the
    container stays alive (and the health endpoint keeps answering) while the
    owner fixes the variable, rather than dying with a traceback.
    """
    delay = _RESTART_DELAY
    attempt = 0
    while True:
        attempt += 1
        try:
            await bot.start(bot_token=BOT_TOKEN)
            logger.info("\u2705 Telegram login successful (attempt %d).", attempt)
            return True
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - never let login crash us
            name = type(exc).__name__
            hint = ""
            if "IncompleteRead" in name or "Connection" in name or "Timeout" in name:
                hint = " (network/MTProto issue — will retry)"
            elif "AuthKey" in name or "Unauthorized" in name or "ApiId" in name:
                hint = " (check BOT_TOKEN / API_ID / API_HASH)"
            logger.error(
                "\u26a0\ufe0f Telegram login failed [%s]: %s%s. Retrying in %ds...",
                name, exc, hint, delay,
            )
            if "Database" in name or "sqlite" in str(exc).lower():
                _reset_broken_session()
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RESTART_DELAY)


async def main():
    # 1. Health server start (used by Railway/Render health checks)
    try:
        await start_health_server()
        logger.info("\u2705 Health server started successfully.")
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001
        logger.error("\u26a0\ufe0f Health server startup failed: %s", e)

    # 2. Enable HTML parse mode for Custom/Premium Emojis & Formatting
    bot.parse_mode = "html"

    # 2b. Install the global button safety net BEFORE any handler can run.
    #     A single flat button list used to raise
    #     "'KeyboardButtonCallback' object is not iterable" and silently kill
    #     the main menu after terms acceptance.  This makes that impossible.
    try:
        from utils.button_safety import (
            install_button_safety,
            install_edit_safety,
            install_callback_safety,
            install_text_safety,
        )
        install_button_safety(bot)
        install_edit_safety(bot)
        install_callback_safety(bot)
        install_text_safety(bot)
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001
        logger.warning("\u26a0\ufe0f Button safety net could not be installed: %s", e)

    # 3. Align support / owner / logger / force-join links with config.py
    try:
        apply_official_links_migration()
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001
        logger.warning("\u26a0\ufe0f Link migration failed: %s", e)

    # 4. Register all plugin handlers (start, buy, admin, callbacks, etc.)
    set_bot_instance(bot)  # lets background tasks (OTP poller) send messages
    try:
        summary = register_all_handlers(bot)
        if isinstance(summary, dict) and summary.get("failed"):
            logger.error(
                "\u26a0\ufe0f Some plugins failed to load: %s. "
                "The bot will still start with the remaining features.",
                ", ".join(summary["failed"]),
            )
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001
        # A loader bug must never take the whole bot down.
        logger.exception("\u26a0\ufe0f Handler registration crashed: %s. Continuing startup...", e)

    # 5. Bot Connect & Start (retries forever — never raises)
    await _connect_with_retry()

    print("==================================================", flush=True)
    print("\U0001F680 NUMBOTT MODULAR (TELETHON) STARTED SUCCESSFULLY!", flush=True)
    print(f"\U0001F4E6 BUILD: {BUILD_TAG}", flush=True)
    print("==================================================", flush=True)

    # 5b. Database self-check.  The "Cannot operate on a closed database"
    # class of bug is invisible until an admin taps a button, so prove the
    # connection is alive (and say which file it is) at every boot.
    try:
        from database import db_health, db_path as _dbp

        health = db_health()
        if health.get("ok"):
            logger.info("\u2705 Database OK: %s", _dbp)
        else:
            logger.error("\u274c Database UNHEALTHY: %s", health.get("error"))
    except Exception as _db_exc:  # pragma: no cover - defensive
        logger.error("Database self-check failed: %s", _db_exc)

    # 6. LZT self-check (non-fatal).
    # A rejected/expired market token used to surface only as
    # "No live accounts found" inside the shop.  Logging the real status at
    # boot makes the cause obvious in Railway/Render logs.
    try:
        from utils.lzt import lzt_client
        key = lzt_client.get_token()
        if not key:
            logger.warning(
                "\u26a0\ufe0f LZT_API_KEY is not set \u2014 live market search "
                "will return nothing. Set it in Admin \u2192 LZT Panel Settings "
                "or as the LZT_API_KEY env var."
            )
        else:
            ok, msg = await asyncio.wait_for(lzt_client.check_connection(), timeout=45)
            plain = msg.replace("<b>", "").replace("</b>", "").replace(
                "<i>", "").replace("</i>", "").replace("<code>", "").replace("</code>", "")
            if ok:
                logger.info("LZT self-check OK: %s", plain)
            else:
                logger.error("LZT self-check FAILED: %s", plain)
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001
        logger.warning("LZT self-check skipped: %s", e)

    # 7. Reconnection Loop
    #    `except Exception` was NOT enough: asyncio.CancelledError derives from
    #    BaseException, escaped this loop and killed the process.
    while True:
        try:
            if not bot.is_connected():
                await bot.connect()
            await bot.run_until_disconnected()
            logger.warning("\u26a0\ufe0f Disconnected cleanly. Reconnecting in 5s...")
        except asyncio.CancelledError:
            # Raised during shutdown (SIGTERM / Ctrl+C) — let it propagate.
            raise
        except BaseException as err:  # noqa: BLE001 - the crash fix
            logger.error(
                "\u26a0\ufe0f Numbott disconnected [%s]: %s. Reconnecting in 5s...",
                type(err).__name__, err,
            )
        await asyncio.sleep(5)


def _supervise() -> None:
    """Run ``main()`` forever, restarting after any unexpected failure."""
    delay = _RESTART_DELAY
    while True:
        try:
            asyncio.run(main())
            # main() only returns if the loop somehow exits.
            logger.warning("\u26a0\ufe0f main() exited unexpectedly. Restarting in %ds...", delay)
        except KeyboardInterrupt:
            logger.info("\U0001F44B Shutdown requested (Ctrl+C). Bye.")
            return
        except SystemExit:
            raise
        except BaseException as exc:  # noqa: BLE001 - last line of defence
            logger.exception(
                "\u274c Unhandled error in main loop [%s]: %s. Restarting in %ds...",
                type(exc).__name__, exc, delay,
            )
        time.sleep(delay)
        delay = min(delay * 2, _MAX_RESTART_DELAY)


if __name__ == "__main__":
    if not validate_runtime_config():
        # Exit cleanly with a readable reason (no traceback in the host logs).
        sys.exit(1)
    try:
        _supervise()
    except KeyboardInterrupt:
        pass
