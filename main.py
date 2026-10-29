import os
import asyncio
import logging
from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID, bot

# Logging Configuration
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs("sessions", exist_ok=True)

# Plugins, Health Server & Utilities
from plugins import register_all_handlers
from utils.health import start_health_server
from utils.helpers import set_bot_instance
from database import apply_official_links_migration


def validate_runtime_config():
    """Ensure all required environment variables are present before booting."""
    missing = []
    if API_ID <= 0:
        missing.append("API_ID")
    if not API_HASH.strip():
        missing.append("API_HASH")
    if not BOT_TOKEN.strip():
        missing.append("BOT_TOKEN")
    if ADMIN_ID <= 0:
        missing.append("ADMIN_ID")

    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Missing required environment variable(s): {names}. "
            "Copy .env.sample to .env locally or configure them in your deployment service."
        )


# ---------------------------------------------------------
# MAIN BOT ASYNC LOOP
# ---------------------------------------------------------
async def main():
    # 1. Health server start (used by Railway/Render health checks)
    try:
        await start_health_server()
        logger.info("✅ Health server started successfully.")
    except Exception as e:
        logger.error(f"⚠️ Health server startup failed: {e}")

    # 2. Enable HTML parse mode for Custom/Premium Emojis & Formatting
    bot.parse_mode = 'html'

    # 3. Align support / owner / logger / force-join links with config.py
    try:
        apply_official_links_migration()
    except Exception as e:
        logger.warning(f"\u26a0\ufe0f Link migration failed: {e}")

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
    except Exception as e:
        # A loader bug must never take the whole bot down.
        logger.exception(f"\u26a0\ufe0f Handler registration crashed: {e}. Continuing startup...")

    # 5. Bot Connect & Start
    try:
        await bot.start(bot_token=BOT_TOKEN)
    except Exception as e:
        logger.error(
            "\u274c Telegram login failed: %s: %s. "
            "Check BOT_TOKEN / API_ID / API_HASH in your host variables.",
            type(e).__name__, e,
        )
        raise
    print("==================================================", flush=True)
    print("🚀 NUMBOTT MODULAR (TELETHON) STARTED SUCCESSFULLY!", flush=True)
    print("==================================================", flush=True)

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
                logger.info(f"LZT self-check OK: {plain}")
            else:
                logger.error(f"LZT self-check FAILED: {plain}")
    except Exception as e:
        logger.warning(f"LZT self-check skipped: {e}")

    # 7. Reconnection Loop
    while True:
        try:
            if not bot.is_connected():
                await bot.connect()
            await bot.run_until_disconnected()
        except Exception as err:
            logger.error(f"⚠️ Numbott disconnected: {err}. Reconnecting in 5s...")
            await asyncio.sleep(5)


if __name__ == '__main__':
    validate_runtime_config()
    asyncio.run(main())
