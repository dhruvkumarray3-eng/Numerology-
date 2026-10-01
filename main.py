import os
import asyncio
import logging
from telethon import TelegramClient, events
from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID, bot

# Logging Configuration
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs("sessions", exist_ok=True)

# Plugins and Utilities
from plugins import register_all_handlers
from utils.health import start_health_server

def validate_runtime_config():
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

async def main():
    # 1. Health server start
    try:
        await start_health_server()
        logger.info("✅ Health server started successfully.")
    except Exception as e:
        logger.error(f"⚠️ Health server startup failed: {e}")

    # 2. Enable HTML mode for rendering Custom/Premium Emojis & Formatting
    bot.parse_mode = 'html'

    # 3. Register all plugin handlers first
    register_all_handlers(bot)

    # 4. Global Callback Catch-All Handler (To prevent infinite loading spinner)
    @bot.on(events.CallbackQuery)
    async def global_callback_debug(e):
        logger.info(f"🔘 CALLBACK RECEIVED: {e.data}")
        # Automatically answer unhandled callbacks to stop button loading spinner
        try:
            await e.answer()
        except Exception:
            pass

    @bot.on(events.NewMessage)
    async def debug_msg(e):
        if e.text:
            logger.info(f"📩 INCOMING MSG from {e.sender_id}: {e.text}")

    # 5. Bot Connect & Start
    await bot.start(bot_token=BOT_TOKEN)
    print("==================================================", flush=True)
    print("🚀 NUMBOTT MODULAR (TELETHON) STARTED SUCCESSFULLY!", flush=True)
    print("==================================================", flush=True)

    # 6. Reconnection Loop
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
