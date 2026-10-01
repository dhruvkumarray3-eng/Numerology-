import os
import sqlite3
import logging
from telethon import TelegramClient
from dotenv import load_dotenv

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                k = key.strip()
                v = value.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v
    except Exception as ex:
        print(f"Failed to load {path}: {ex}")

load_env_file()

def env_int(name, default=0):
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "": return default
    return int(str(raw).strip())

def format_join_url(url: str) -> str:
    """Normalizes any Telegram link or username into a valid https://t.me/... URL."""
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("t.me/") or url.startswith("telegram.me/"):
        return f"https://{url}"
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    if not (url.startswith("-") or url.isdigit()):
        return f"https://t.me/{url}"
    return url

def env_list(name, default_csv=""):
    raw = os.getenv(name, default_csv)
    if not raw: return []
    import re
    items = [item.strip() for item in re.split(r'[\s,]+', raw) if item.strip()]
    if name == "JOIN_URLS":
        return [format_join_url(item) for item in items if item]
    return items

API_ID = env_int("API_ID", 0)
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if API_ID <= 0 or not API_HASH.strip():
    raise RuntimeError(
        "Missing required Telegram configuration: set API_ID and API_HASH "
        "before starting the bot."
    )

bot = TelegramClient('bot_session', API_ID, API_HASH, connection_retries=None, retry_delay=3, auto_reconnect=True)
bot.parse_mode = 'html'

ADMIN_ID = env_int("ADMIN_ID", env_int("SUPER_ADMIN_ID", env_int("OWNER_ID", 0)))
SUPER_ADMIN_ID = env_int("SUPER_ADMIN_ID", ADMIN_ID)
SUPER_ADMINS = {uid for uid in (SUPER_ADMIN_ID, ADMIN_ID) if uid}

def is_super_admin(uid: int) -> bool:
    try:
        return int(uid) in SUPER_ADMINS
    except (ValueError, TypeError):
        return False

# CHANNELS
LOG_CHANNEL_ID = env_int("LOG_CHANNEL_ID", 0)
LOG_CHANNEL_ID_2 = env_int("LOG_CHANNEL_ID_2", 0)
LOG_CHANNELS = [ch for ch in [LOG_CHANNEL_ID, LOG_CHANNEL_ID_2] if ch]
CHECK_CHANNELS = env_list("CHECK_CHANNELS", "")
JOIN_URLS = env_list("JOIN_URLS", "")

# LINKS & MEDIA
TERMS_URL = os.getenv("TERMS_URL", "").strip() or "https://github.com/dhruvkumarray3-eng/Numerology-/blob/main/TERMS_AND_CONDITIONS.md"
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip() or "https://t.me/Sexypremiums"
UPDATES_URL = os.getenv("UPDATES_URL", "").strip() or "https://t.me/mafiaXupdates"
CWALLET_QR = os.getenv("CWALLET_QR", "")
CWALLET_ID = os.getenv("CWALLET_ID", "")

# UPI API DETAILS
UPI_MID = os.getenv("UPI_MID", "")
UPI_ID = os.getenv("UPI_ID", "")

OTP_REGEX = r"\b\d{4,8}\b"
AUTO_CANCEL_SECONDS = 600

# ================= PREMIUM EMOJIS =================
USE_PREMIUM_EMOJIS = os.getenv("USE_PREMIUM_EMOJIS", "1").strip().lower() not in {"0", "false", "no", "off"}
PREMIUM_EMOJIS = {
    "heart_fire": 5375125990118793401,
    "lightning": 5409271925014801629,
    "location": 5409119256107297715,
    "flower": 5408995930416362034,
    "check": 5409098988156629257,
    "crown": 5409166771330494453,
    "kiss": 5409380965644514142,
    "skull": 5409337058193847247,
    "xmas": 5409320020058584473,
    "monkey": 5408832111773757273,
    "gift": 5440627033111557670,
    "angel": 6203982793379154737,
    "devil": 6064310143380625195,
}

def tg_emoji(name, fallback):
    emoji_id = PREMIUM_EMOJIS.get(name)
    if USE_PREMIUM_EMOJIS and emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

PE_HEART = tg_emoji("heart_fire", "❤️‍🔥")
PE_LIGHTNING = tg_emoji("lightning", "⚡")
PE_LOCATION = tg_emoji("location", "📍")
PE_FLOWER = tg_emoji("flower", "🌸")
PE_CHECK = tg_emoji("check", "✅")
PE_CROWN = tg_emoji("crown", "👑")
PE_KISS = tg_emoji("kiss", "😘")
PE_SKULL = tg_emoji("skull", "💀")
PE_XMAS = tg_emoji("xmas", "🎄")
PE_MONKEY = tg_emoji("monkey", "🐵")
PE_GIFT = tg_emoji("gift", "🎁")
PE_ANGEL = tg_emoji("angel", "😇")
PE_DEVIL = tg_emoji("devil", "😈")

P_YES = PE_CHECK
P_NO = '❌'
P_PKG = '📦'
P_MONEY = '💰'
P_USDT = '💲'
P_INR = '₹'
P_TG = '✈️'
P_GIFT = PE_GIFT
P_STATS = '📊'
P_CARD = '💳'
P_USERS = '👥'
P_CAL = '📅'
P_PC = '💻'
P_EYE = '👁️'
P_UPI = '🏦'
P_CW = '👛'
P_ON = '🟢'
P_OFF = '🔴'
P_ID = '🆔'
P_KEY = '⌨️'
P_GLOBE = PE_LOCATION
P_CART = '🛒'
P_STORE = '🏬'
P_OTP = '🔢'
P_2FA = '🔐'
P_FLAG = '🏳️'
P_PHONE = '📱'
P_WAIT = '⏳'
P_TIME = '⏰'
P_WARN = '⚠️'
P_DOC = '📃'
P_SOS = '🆘'
P_ASST = '🤖'
P_ACC = '👤'

# ==========================================
# LZT MARKET & CUSTOM EMOJI CONFIGURATIONS
# ==========================================

LZT_API_KEY = os.getenv("LZT_API_KEY", "")
USDT_TO_INR = float(os.getenv("USDT_TO_INR", "88.0"))       # Base USDT rate
ADMIN_PROFIT_INR = float(os.getenv("ADMIN_PROFIT_INR", "50.0")) # Margin in INR

PREMIUM_EMOJIS = {
    "TELEGRAM": "6028346797368283073",   # ✈️ Telegram Icon
    "APPLE": "5775870512127283512",      # 🍏 Apple
    "STAR": "6028338546736107668",       # ⭐️ Star
    "GIFT": "5307949733786976205",       # 🎁 Gift
    "CHECK_RED": "6296577138615125756",  # Red Check
    "HEART": "6298356878573307709",      # ❤️ Heart
    "VIP": "6219549292458150316",        # 👑 VIP Crown
    "EYE": "6220029508456548253",        # 👁 Eye
    "ERROR_CROSS": "6298671811345254603",# 😭 Error / Cancel
    "SUCCESS_GREEN": "6296367896398399651", # Green Check
    "FIRE": "6235291666152953756",       # 🔥 Fire
    "LIGHTNING": "5224607267797606837",  # ⚡ Lightning
    "LOGIN": "6242333741776115895",      # LOG IN Badge
    "LOGOUT": "6240145013557173263",     # LOG OUT Badge
    "CANDY": "6242174063481984917",      # 🍭 Candy
    "NUMBER": "5823219494318773845",     # 🔢 Number
    "SHIELD": "6086672466132865380",     # 🛡 Shield
    "SPARKLE": "6086639764251873025",    # 💫 Sparkle
    "SMILE": "6086690887247597839",      # 🙂 Smile
    "DEVIL": "6089217174126203362",      # 👹 Troll / Devil
    "DIAMOND": "6086778246882399112",    # 💎 Diamond
    "PERCENT": "6093421221259514937",    # 100%
    "PINK_PLANE": "6255963511252322252", # Pink Plane
    "PURPLE_STAR": "6136464120779638846"# Purple Star
}

def get_emoji(key: str) -> str:
    """Renders HTML-compatible Telegram Custom Premium Emoji"""
    emoji_id = PREMIUM_EMOJIS.get(key)
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}"></tg-emoji>'
    return ""

BEP20_ADDRESS = os.getenv("BEP20_ADDRESS", os.getenv("CWALLET_ID", "")).strip()

    

