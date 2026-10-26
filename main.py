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

    # 3. Register all plugin handlers (start, buy, admin, callbacks, etc.)
    register_all_handlers(bot)

    # 4. Bot Connect & Start
    await bot.start(bot_token=BOT_TOKEN)
    print("==================================================", flush=True)
    print("🚀 NUMBOTT MODULAR (TELETHON) STARTED SUCCESSFULLY!", flush=True)
    print("==================================================", flush=True)

    # 5. Reconnection Loop
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
