import os
import re
import html
import asyncio
import logging
from telethon import TelegramClient, events
from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID, bot

# Logging Configuration
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs("sessions", exist_ok=True)

# Plugins, Health Server & Utilities
from plugins import register_all_handlers
from utils.health import start_health_server

# Imports for helpers (Ensure these exist in your helper/utils files, or adjust imports as per project structure)
try:
    from utils.helpers import get_countries_list, get_flag_by_country_name, style_btn, COUNTRY_CODES
except ImportError:
    # Fallback definitions if imported elsewhere via plugins
    pass

# Global In-memory States
search_state = {}
user_states = {}

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

from telethon import Button

# ---------------------------------------------------------
# HELPER: STYLE BUTTON (Supports Custom Icons & Colors)
# ---------------------------------------------------------
def style_btn(text, data, color_type="primary", icon=None):
    # Yeh function icon aur color arguments ko handle karega 
    # taaki Telethon mein unexpected keyword argument ka error na aaye.
    return Button.inline(text, data)


# ---------------------------------------------------------
# HELPER: SHOW BUY MENU UI
# ---------------------------------------------------------
async def show_buy_menu(event):
    btns = [
        [style_btn("🔍 Search Country", "btn_search_country", "primary", icon=6154249597532248059)],
        [
            style_btn("🟢 Non-Spam / Clean", "cat_clean", "success", icon=5409320020058584473),
            style_btn("🟡 Spam / Used", "cat_spam", "warning", icon=6129888444245089008)
        ],
        [style_btn("🎯 More Account Filters", "cat_filters", "success", icon=6154249597532248059)],
        [style_btn("🌐 All Countries (Fresh)", "cat_all_countries", "primary", icon=6154249597532248059)],
        [style_btn("🏛 Old / Aged Accounts", "cat_aged", "primary", icon=6154249597532248059)],
        [style_btn("🔙 Back to Dashboard", "main_dashboard", "danger", icon=6129812419028982717)]
    ]
    
    text = "<blockquote expandable>🛒 <b>𝐒𝐄𝐋𝐄𝐂𝐓 𝐀𝐂𝐂𝐎𝐔𝐍𝐓 𝐂𝐀𝐓𝐄𝐆𝐎𝐑𝐘:</b>\n\n<i>Choose a category below to browse accounts or search by country.</i></blockquote>"
    await event.respond(text, buttons=btns)


# ---------------------------------------------------------
# 1. CALLBACK QUERY HANDLER (Search Country & Navigation Buttons)
# ---------------------------------------------------------
@bot.on(events.CallbackQuery)
async def main_callback_handler(event):
    data = event.data.decode('utf-8') if isinstance(event.data, bytes) else str(event.data)
    uid = event.sender_id

    if data == "btn_search_country":
        # Enable search mode
        search_state[uid] = True
        user_states[uid] = "AWAITING_COUNTRY"
        
        msg = "🔎 <b>𝐄𝐧𝐭𝐞𝐫 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 𝐍𝐚𝐦𝐞 𝐨𝐫 𝐃𝐢𝐚𝐥 𝐂𝐨𝐝𝐞:</b>\n\n<i>Example: India, +91, USA, +1</i>"
        await event.edit(msg, buttons=[[style_btn("🔙 Back to Menu", "buy_menu_main", "danger", icon=6129812419028982717)]])

    elif data == "buy_menu_main":
        # Reset search mode on back button press
        search_state[uid] = False
        user_states[uid] = None
        await show_buy_menu(event)


# ---------------------------------------------------------
# 2. REPLY KEYBOARD DISPATCHER ("BUY ACCOUNT" Button Fix)
# ---------------------------------------------------------
@bot.on(events.NewMessage)
async def reply_keyboard_dispatcher(event):
    if not event.text or event.text.startswith("/"):
        return
        
    text = event.text.strip()
    uid = event.sender_id

    # Clean text to ignore custom emojis/formatting in string comparison
    clean_btn_text = re.sub(r'[^\w\s]', '', text).strip().upper()

    # 🛒 BUY ACCOUNT Button Trigger
    if "BUY ACCOUNT" in clean_btn_text or text == "🛒 BUY ACCOUNT":
        search_state[uid] = False
        user_states[uid] = None
        await show_buy_menu(event)
        raise events.StopPropagation

    # Reset states when clicking other navigation menu buttons
    elif any(cmd in clean_btn_text for cmd in ["STOCK", "PROFILE", "BALANCE", "START", "CLOSE"]):
        search_state[uid] = False
        user_states[uid] = None


# ---------------------------------------------------------
# 3. SEARCH INPUT PROCESSOR (Country Search Fix)
# ---------------------------------------------------------
@bot.on(events.NewMessage)
async def process_combined_text_input(event):
    if not event.text or event.text.startswith("/"):
        return
        
    uid = event.sender_id
    
    # Process text input only when user is in search state
    if search_state.get(uid) or user_states.get(uid) == "AWAITING_COUNTRY":
        search_state[uid] = False
        user_states[uid] = None
        
        raw_text = event.text.strip()
        query_lower = raw_text.lower()
        clean_num = re.sub(r"[^\d]", "", raw_text)

        try:
            countries_all = await get_countries_list()
        except Exception as e:
            logger.error(f"Error fetching country list: {e}")
            countries_all = []

        matches = []

        for c_entry in countries_all:
            if isinstance(c_entry, (tuple, list)):
                c_name, count = c_entry[0], c_entry[1]
            else:
                c_name, count = str(c_entry), 0

            c_lower = c_name.lower()
            
            dial_code = str(
                COUNTRY_CODES.get(c_name) or 
                COUNTRY_CODES.get(c_lower) or 
                COUNTRY_CODES.get(c_name.title()) or ''
            ).replace("+", "").strip()

            if (query_lower in c_lower) or (clean_num and clean_num == dial_code):
                matches.append((c_name, count))

        if not matches:
            return await event.respond(
                f"❌ No country found matching '<code>{html.escape(raw_text)}</code>'.\n"
                f"Please try again with a valid country name or code (e.g. India, +91, +1).", 
                buttons=[[style_btn("🔙 Back to Menu", "buy_menu_main", "danger", icon=6129812419028982717)]]
            )

        btns = []
        for c_name, count in matches[:10]:
            flag = get_flag_by_country_name(c_name)
            cnt_str = f"({count})" if count else "(Available)"
            btns.append([style_btn(f"{flag} {c_name} {cnt_str}", f"bc|bulk|{c_name}", "primary", icon=6154249597532248059)])
            
        btns.append([style_btn("🔙 Back to Menu", "buy_menu_main", "danger", icon=6129812419028982717)])
        
        await event.respond(
            f"<blockquote expandable>🔎 <b>𝐒𝐞𝐚𝐫𝐜𝐡 𝐑𝐞𝐬𝐮𝐥𝐭𝐬 𝐟𝐨𝐫 '{html.escape(raw_text)}':</b></blockquote>", 
            buttons=btns
        )


# ---------------------------------------------------------
# MAIN BOT ASYNC LOOP
# ---------------------------------------------------------
async def main():
    # 1. Health server start
    try:
        await start_health_server()
        logger.info("✅ Health server started successfully.")
    except Exception as e:
        logger.error(f"⚠️ Health server startup failed: {e}")

    # 2. Enable HTML parse mode for Custom/Premium Emojis & Formatting
    bot.parse_mode = 'html'

    # 3. Register all plugin handlers
    register_all_handlers(bot)

    # 4. Global Callback Catch-All Handler (Prevents infinite button loading spinner)
    @bot.on(events.CallbackQuery)
    async def global_callback_debug(e):
        logger.info(f"🔘 CALLBACK RECEIVED: {e.data}")
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
