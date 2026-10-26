import os
import asyncio
import time
import zipfile
import re
import html
import json
import logging
import requests
from telethon import events, Button, TelegramClient, types
from telethon.errors import (
    MessageNotModifiedError, PhoneNumberInvalidError, PhoneNumberOccupiedError,
    PhoneCodeInvalidError, PhoneCodeExpiredError,
    FreshChangePhoneForbiddenError, FloodWaitError
)
from telethon.errors.rpcerrorlist import MessageIdInvalidError
from telethon.tl.functions.account import SendChangePhoneCodeRequest, ChangePhoneRequest

from database import (
    cur, db, get_flag_by_country_name, get_bot_mode, get_panel_price,
    get_lzt_key, get_change_number_fee, COUNTRY_CODES, is_admin, get_log_channels_db
)
from config import (
    PE_LOCATION, PE_GIFT, PE_LIGHTNING, PE_CHECK, P_MONEY, P_PKG, P_CARD, P_WARN,
    P_NO, P_YES, P_INR, P_TIME, P_FLAG, P_OTP, P_2FA, P_PHONE, AUTO_CANCEL_SECONDS,
    OTP_REGEX, bot, logger, API_ID, API_HASH, LZT_API_KEY, USDT_TO_INR
)
from utils.keyboards import style_btn, matches_menu
from utils.markup import format_dual_from_inr, format_dual_price
from utils.states import active_orders, session_buy_state, get_user_lock
from utils.lzt import lzt_client, COUNTRY_TO_LZT, get_lzt_code
from utils import stock_details as stock_card

try:
    from utils.search_settings import (
        int_setting as _ss_int,
        is_live_search_enabled as _ss_live,
        show_zero_counts as _ss_show_zero,
        resolve_mode as _ss_mode,
    )
except Exception:  # pragma: no cover - defensive
    def _ss_int(key, fallback):
        try:
            return int(fallback)
        except Exception:
            return fallback

    def _ss_live():
        return True

    def _ss_show_zero():
        return False

    def _ss_mode(mode):
        return mode

search_state = {}
change_number_state = {}
user_states = {}


def _lzt_live():
    """True when a live LZT market key is configured.

    The market is the primary stock source.  BOT_MODE only decides whether
    *local* (manually uploaded) stock is preferred first -- it must never
    disable live search, otherwise a bot on the default 'manual' mode shows
    "No live accounts found" while the market is full of accounts.
    """
    if not _ss_live():
        return False
    try:
        return bool(get_lzt_key())
    except Exception:
        return bool(LZT_API_KEY)

# Comprehensive Country & Dial Code Fallback Map
COUNTRY_MAP = {
    "india": "India", "in": "India", "+91": "India", "91": "India",
    "usa": "USA", "us": "USA", "+1": "USA", "1": "USA",
    "south africa": "South Africa", "+27": "South Africa", "27": "South Africa",
    "uk": "UK", "gb": "UK", "+44": "UK", "44": "UK",
    "canada": "Canada", "+1ca": "Canada",
}

# ---------------------------------------------------------
# 🌍 COUNTRY SEARCH HELPERS
# ---------------------------------------------------------
def _normalize_country_text(value):
    """Lowercase and strip everything except letters/digits for fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


# Build a normalized country-name -> dial-code map from COUNTRY_CODES.
# Handles compound names such as "USA/Canada" by registering each part.
COUNTRY_NAME_TO_DIAL = {}
for _dial, (_cname, _flag) in COUNTRY_CODES.items():
    COUNTRY_NAME_TO_DIAL.setdefault(_normalize_country_text(_cname), _dial)
    for _part in re.split(r"[/,&]", _cname):
        _part_key = _normalize_country_text(_part)
        if _part_key:
            COUNTRY_NAME_TO_DIAL.setdefault(_part_key, _dial)


def country_matches_query(query, country_name):
    """
    Return True if a free-text query (country name, alias, ISO-2/ISO-3 or dial
    code) matches the given country name.

    Delegates to the universal resolver in ``utils.country_search`` so that
    ``Japan``, ``JP``, ``JPN``, ``+81`` and ``81`` all match the same country.
    """
    try:
        from utils.country_search import country_matches
        return bool(country_matches(query, country_name))
    except Exception:
        pass

    # --- defensive fallback (never expected to run) ---
    raw_query = str(query or "").strip()
    q = _normalize_country_text(raw_query)
    n = _normalize_country_text(country_name)
    if not q or not n:
        return False
    if q in n or n in q:
        return True
    alias = COUNTRY_MAP.get(raw_query.lower())
    if alias and _normalize_country_text(alias) == n:
        return True
    q_digits = re.sub(r"\D", "", raw_query)
    if q_digits:
        dial = COUNTRY_NAME_TO_DIAL.get(n)
        if dial and (dial == q_digits or dial.startswith(q_digits) or q_digits.startswith(dial)):
            return True
    return False


def search_countries(countries_all, query):
    """Filter and de-duplicate a list of (country, count) tuples by query."""
    matches = []
    seen = set()
    for entry in countries_all or []:
        if isinstance(entry, (tuple, list)):
            c_name, count = entry[0], entry[1]
        else:
            c_name, count = str(entry), 0

        if country_matches_query(query, c_name):
            key = _normalize_country_text(c_name)
            if key not in seen:
                seen.add(key)
                matches.append((c_name, count))
    return matches


async def safe_edit_message(event, text, buttons=None):
    """Safely edit message to handle MessageIdInvalidError gracefully."""
    try:
        await event.edit(text, buttons=buttons)
    except MessageIdInvalidError:
        logger.warning("Message ID invalid, sending a new message instead.")
        await event.respond(text, buttons=buttons)
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await event.respond(text, buttons=buttons)

def get_active_order_card(order, phone, is_admin_user=False):
    fee = get_change_number_fee()
    fee_badge = f" (+₹{fee})" if fee > 0 else " (FREE)"
    msg = (f"<blockquote expandable>"
           f"<tg-emoji emoji-id=\"5409320020058584473\">⚡</tg-emoji> <b>𝐎𝐑𝐃𝐄𝐑 𝐀𝐂𝐓𝐈𝐕𝐄!</b> <tg-emoji emoji-id=\"5408995930416362034\">💎</tg-emoji>\n\n"
           f"📱 <b>𝐏𝐡𝐨𝐧𝐞:</b> <code>+{phone}</code>\n"
           f"{order['c_icon']} <b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> {order['country']}\n"
           f"🔐 <b>𝟐𝐅𝐀 𝐏𝐚𝐬𝐬𝐰𝐨𝐫𝐝:</b> <code>{order['twofa']}</code>\n\n"
           f"🔻 <b>𝐈𝐧𝐬𝐭𝐫𝐮𝐜𝐭𝐢𝐨𝐧𝐬:</b>\n"
           f"1. 𝐎𝐩𝐞𝐧 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦 & 𝐀𝐝𝐝 𝐀𝐜𝐜𝐨𝐮𝐧𝐭 (<code>+{phone}</code>).\n"
           f"2. ⏳ <b>𝐏𝐥𝐞𝐚𝐬𝐞 𝐰𝐚𝐢𝐭!</b> 𝐓𝐡𝐞 ʙᴏᴛ ɪs ᴀᴄᴛɪᴠᴇʟʏ ʟɪsᴛᴇɴɪɴɢ ғᴏʀ ʏ𝐨𝐮ʀ 𝐎𝐓𝐏.\n\n"
           f"<i><tg-emoji emoji-id=\"5409320020058584473\">✨</tg-emoji> 𝐘𝐨𝐮 𝐜𝐚𝐧 𝐚𝐥𝐬𝐨 𝐭𝐚𝐩 '🔄 𝐂𝐡𝐚𝐧𝐠𝐞 𝐭𝐨 𝐌𝐲 𝐍𝐮𝐦𝐛𝐞𝐫' 𝐭𝐨 𝐦𝐢𝐠𝐫𝐚𝐭𝐞 𝐭𝐡𝐢s 𝐚𝐜𝐜𝐨𝐮𝐧𝐭 𝐝𝐢𝐫𝐞𝐜𝐭𝐥𝐲!</i></blockquote>")
    
    btns = [
        [style_btn(f"🔄 𝐂𝐡𝐚𝐧𝐠𝐞 𝐭𝐨 𝐌𝐲 𝐍𝐮𝐦𝐛𝐞𝐫{fee_badge}", f"chg_num|{phone}", "success", icon=5409320020058584473)],
        [
            style_btn("🔄 𝐆𝐞𝐭 𝐎𝐓𝐏 𝐀𝐠𝐚𝐢𝐧", f"get_otp_again|{phone}", "primary", icon=5408995930416362034),
            style_btn("✅ 𝐅𝐢𝐧𝐢𝐬𝐡 𝐎𝐫𝐝𝐞𝐫", f"finish_order|{phone}", "primary", icon=5409320020058584473)
        ]
    ]
    if is_admin_user:
        btns.append([style_btn("❌ [Admin] Cancel & Refund", f"cancel_order|{phone}", "danger", icon=6129888444245089008)])
    return msg, btns

_LIVE_COUNTRY_CACHE = {"ts": 0.0, "counts": {}}
_LIVE_COUNTRY_TTL = 900  # 15 minutes


async def _live_country_counts():
    """Cached live per-country stock counts from the LZT panel (honest numbers)."""
    now = time.time()
    if _LIVE_COUNTRY_CACHE["counts"] and (now - _LIVE_COUNTRY_CACHE["ts"]) < _LIVE_COUNTRY_TTL:
        return _LIVE_COUNTRY_CACHE["counts"]

    counts = {}
    try:
        if get_lzt_key():
            counts = await asyncio.wait_for(
                lzt_client.get_country_counts(max_pages=2), timeout=9
            )
    except Exception as e:
        logger.debug(f"live country counts failed: {e}")
        counts = {}

    # Merge in the exact server-side totals we learned from real searches
    # (search_items records totalItems per country).  These are far more
    # accurate than sampling a couple of pages of the global cheap list.
    try:
        for c_name, total in (getattr(lzt_client, "country_totals", {}) or {}).items():
            code = get_lzt_code(c_name)
            if code and total:
                counts[code] = max(counts.get(code, 0), int(total))
    except Exception:
        pass

    if counts:
        _LIVE_COUNTRY_CACHE["ts"] = now
        _LIVE_COUNTRY_CACHE["counts"] = counts
    return counts


async def get_countries_list():
    """Every country the bot can sell, with an honest live/local count.

    The list is always populated (all 198 ISO countries) so country search
    never dead-ends just because one mode/panel has no stock right now.  The
    count next to each country is the real number available (0 = none).
    """
    # Canonical country names (deduplicated, no aliases).
    try:
        from utils.country_search import all_countries
        base_names = [c["name"] for c in all_countries()]
    except Exception:
        base_names = sorted(set(COUNTRY_TO_LZT.keys()))

    # Local (manual) stock is always merged in, whatever the mode.
    local_counts = {}
    try:
        for c_name, count in cur.execute(
            "SELECT country_name, COUNT(*) FROM stock WHERE available=1 "
            "GROUP BY country_name"
        ).fetchall():
            if c_name:
                local_counts[c_name] = int(count or 0)
    except Exception:
        local_counts = {}

    all_c = list(base_names)
    try:
        customs = cur.execute("SELECT name FROM custom_countries").fetchall()
        for (c,) in customs:
            if c and c not in all_c:
                all_c.append(c)
    except Exception:
        pass

    # LIVE LZT counts whenever a market key exists.  This used to be gated on
    # BOT_MODE in ('panel','hybrid'), so a bot left on the default 'manual'
    # mode never asked LZT at all and every country showed 0 -> "No live
    # accounts found" even though the market had thousands of accounts.
    live = await _live_country_counts() if _lzt_live() else {}

    country_dict = {}
    for c_name in all_c:
        code = get_lzt_code(c_name)
        country_dict[c_name] = live.get(code, 0) if code else 0

    for c_name, count in local_counts.items():
        country_dict[c_name] = max(country_dict.get(c_name, 0), count)

    return sorted(country_dict.items(), key=lambda x: x[0])

YEAR_BADGES = {
    2026: "✨ 2026 (Fresh)",
    2025: "🥉 2025 (1 Year Old)",
    2024: "🥈 2024 (2 Years Old)",
    2023: "🥇 2023 (3 Years Old)",
    2022: "💎 2022 (4 Years Old)",
    2021: "👑 2021 (5 Years Old)",
    2020: "🔥 2020 (6 Years Old)",
    2019: "⚡ 2019 & Older (Vintage)"
}

FILTERS_LIST = [
    ("stars", "⭐ 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦 𝐒𝐭𝐚𝐫𝐬 (𝐁𝐚𝐥𝐚𝐧𝐜𝐞)", 5409320020058584473),
    ("premium", "👑 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦 𝐏𝐫𝐞𝐦𝐢𝐮𝐦", 5408995930416362034),
    ("no_email", "🚫 𝐍𝐨 𝐄𝐦𝐚𝐢𝐥 𝐁𝐨𝐮𝐧𝐝 (𝐃𝐢𝐫𝐞𝐜𝐭 𝐎𝐓𝐏)", 5409320020058584473),
    ("with_email", "📧 𝐄𝐦𝐚𝐢𝐥 𝐁𝐨𝐮𝐧𝐝 (𝐖𝐢𝐭𝐡 𝐌𝐚𝐢𝐥)", 5408995930416362034),
    ("no_2fa", "🔓 𝐍𝐨 𝟐𝐅𝐀 (𝟏-𝐂𝐥𝐢𝐜𝐤 𝐋𝐨𝐠𝐢𝐧)", 5409320020058584473),
    ("with_2fa", "🔒 𝟐𝐅𝐀 𝐄𝐧𝐚𝐛𝐥𝐞𝐝 (𝐏𝐚𝐬𝐬 𝐈𝐧𝐜𝐥𝐮𝐝𝐞𝐝)", 5408995930416362034),
    ("dc5", "🌐 𝐃𝐂 𝟓 (𝐀𝐬𝐢𝐚 / 𝐈𝐧𝐝𝐢𝐚 𝐏𝐢𝐧𝐠)", 5409320020058584473),
    ("aged", "🏛️ 𝐀𝐠𝐞𝐝 / 𝐎𝐥𝐝 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬", 5408995930416362034),
]

FILTER_BADGES = {
    "stars": "⭐ 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦 𝐒𝐭𝐚𝐫𝐬",
    "premium": "👑 𝐓𝐞𝐥𝐞𝐠𝐫𝐚𝐦 𝐏𝐫𝐞𝐦𝐢𝐮𝐦",
    "no_email": "🚫 𝐍𝐨 𝐄𝐦𝐚𝐢𝐥 𝐁𝐨𝐮𝐧𝐝 (𝐃𝐢𝐫𝐞𝐜𝐭 𝐎𝐓𝐏)",
    "with_email": "📧 𝐄𝐦𝐚𝐢𝐥 𝐁𝐨𝐮𝐧𝐝 (𝐖𝐢𝐭𝐡 𝐌𝐚𝐢𝐥)",
    "nonspam": "🟢 𝐍𝐨𝐧-𝐒𝐩𝐚𝐦 (𝟏𝟎𝟎% 𝐂𝐥𝐞𝐚𝐧)",
    "spam": "🟡 𝐒𝐩𝐚𝐦 / 𝐔𝐬𝐞𝐝 (𝐂𝐡𝐞𝐚𝐩)",
    "no_2fa": "🔓 𝐍𝐨 𝟐𝐅𝐀 (𝟏-𝐂𝐥𝐢𝐜𝐤 𝐋𝐨𝐠𝐢𝐧)",
    "with_2fa": "🔒 𝟐𝐅𝐀 𝐄𝐧𝐚𝐛𝐥𝐞𝐝 (𝐏𝐚𝐬𝐬 𝐈𝐧𝐜𝐥𝐮𝐝𝐞𝐝)",
    "dc5": "🌐 𝐃𝐂 𝟓 (𝐀𝐬𝐢𝐚)",
    "aged": "🏛️ 𝐀𝐠𝐞𝐝 / 𝐎𝐥𝐝",
    "bulk": "🌍 𝐒𝐭𝐚𝐧𝐝𝐚𝐫𝐝"
}

async def show_filters_catalog(event, page=1):
    limit = 4
    offset = (page - 1) * limit
    items = FILTERS_LIST[offset:offset+limit]
    total = len(FILTERS_LIST)
    total_pages = max(1, (total + limit - 1) // limit)

    msg = (f"<blockquote expandable><tg-emoji emoji-id=\"5409320020058584473\">🎯</tg-emoji> <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐚𝐧 𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐅𝐢𝐥𝐭𝐞𝐫:</b> (𝐏𝐚𝐠𝐞 {page}/{total_pages})\n\n"
           f"<i><tg-emoji emoji-id=\"5408995930416362034\">✨</tg-emoji> 𝐂𝐡𝐨𝐨𝐬𝐞 𝐚 𝐬𝐩𝐞𝐜𝐢𝐟𝐢𝐜 𝐚𝐜𝐜𝐨𝐮𝐧𝐭 𝐭𝐲𝐩𝐞 𝐛𝐞𝐥𝐨𝐰 𝐭𝐨 𝐛𝐫𝐨𝐰𝐬𝐞 𝐜𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬:</i></blockquote>")
    
    btns = []
    for f_id, label, icon in items:
        if f_id == "aged":
            btns.append([style_btn(label, "by_years_menu", "primary", icon=icon)])
        else:
            btns.append([style_btn(label, f"pg_c|{f_id}|1", "primary", icon=icon)])

    nav = []
    if page > 1: nav.append(style_btn("⬅️ 𝐏𝐫𝐞𝐯", f"pg_filters|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total: nav.append(style_btn("𝐍𝐞𝐱𝐭 ➡️", f"pg_filters|{page+1}", "primary", icon=6129732880529628243))
    if nav: btns.append(nav)

    btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)])

    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

async def show_buy_menu(event):
    msg = (f"<blockquote expandable><tg-emoji emoji-id=\"5408995930416362034\">🎁</tg-emoji> <b>𝐒𝐄𝐋𝐄𝐂𝐓 𝐀𝐂𝐂𝐎𝐔𝐍𝐓 𝐂𝐀𝐓𝐄𝐆𝐎𝐑𝐘</b> <tg-emoji emoji-id=\"5409320020058584473\">💎</tg-emoji>\n\n"
           f"🔍 <b>𝐒𝐞𝐚𝐫𝐜𝐡 𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> 𝐐𝐮𝐢𝐜𝐤 𝐥𝐨𝐨𝐤𝐮𝐩 𝐛𝐲 𝐧𝐚𝐦𝐞 𝐨𝐫 𝐝𝐢𝐚𝐥 𝐜𝐨𝐝𝐞 (+91, +55...)\n"
           f"🟢 <b>Good Quality:</b> 100% Spam-Block Free (DM & Personal Use).\n"
           f"🟡 <b>Cheap:</b> Budget Accounts (Channel Joiners & Members).\n"
           f"🎯 <b>𝐌𝐨𝐫𝐞 𝐅𝐢𝐥𝐭𝐞𝐫𝐬:</b> 𝐒𝐭𝐚𝐫𝐬, 𝐄𝐦𝐚𝐢𝐥, 2𝐅𝐀, 𝐏𝐫𝐞𝐦𝐢𝐮𝐦, 𝐃𝐂...\n"
           f"🌍 <b>𝐀𝐥𝐥 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬:</b> 𝐁𝐫𝐨𝐰𝐬𝐞 50+ 𝐜𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬 𝐬𝐭𝐨𝐜𝐤 (𝐅𝐫𝐞𝐬𝐡 & 𝐀𝐥𝐥).\n"
           f"🏛 <b>𝐎𝐥𝐝 / 𝐀𝐠𝐞𝐝 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬:</b> 𝐅𝐢𝐥𝐭𝐞𝐫 𝐛𝐲 𝐒𝐩𝐞𝐜𝐢𝐟𝐢𝐜 𝐘𝐞𝐚𝐫 (2025, 2024, 2023...).</blockquote>")
    btns = [
        [style_btn("🔍 𝐒𝐞𝐚𝐫𝐜𝐡 𝐂𝐨𝐮𝐧𝐭𝐫𝐲", "search_country_btn", "primary", icon=5409098988156629257)],
        [style_btn("📱 𝐀𝐥𝐥 𝐚𝐩𝐩𝐬 𝐚𝐜𝐜", "all_apps_menu", "success", icon=5409320020058584473),
         style_btn("💬 𝐁𝐮𝐲 𝐖𝐩 𝐀𝐜𝐜", "buy_wp_acc", "success", icon=5408995930416362034)],
        [
            style_btn("✅ 𝓖𝓸𝓸𝓭 𝓠𝓾𝓪𝓵𝓲𝓽𝔂 𝓣𝓖 𝓐𝓬𝓬", "pg_c|nonspam|1", "success", icon=5409320020058584473),
            style_btn("💰 𝓒𝓱𝓮𝓪𝓹 𝓣𝓖 𝓐𝓬𝓬", "pg_c|spam|1", "primary", icon=5408995930416362034)
        ],
        [style_btn("🎯 𝐌𝐨𝐫𝐞 𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐅𝐢𝐥𝐭𝐞𝐫𝐬 (𝐒𝐭𝐚𝐫𝐬/2𝐅𝐀...)", "pg_filters|1", "success", icon=5409320020058584473)],
        [style_btn("🌍 𝐀𝐥𝐥 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬 (𝐅𝐫𝐞𝐬𝐡 & 𝐀𝐥𝐥)", "pg_c|bulk|1", "primary", icon=6154249597532248059)],
        [style_btn("🏛️ 𝐎𝐥𝐝 / 𝐀𝐠𝐞𝐝 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬 (𝐛𝐲 𝐘𝐞𝐚𝐫)", "by_years_menu", "primary", icon=5408995930416362034)],
        [style_btn("📱 𝓑𝓪𝓼𝓲𝓬 𝓣𝓮𝓵𝓮𝓰𝓻𝓪𝓶 𝓐𝓬𝓬𝓸𝓾𝓷𝓽𝓼", "mtg_home", "success", icon=5409320020058584473)],
        [style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐃𝐚𝐬𝐡𝐛𝐨𝐚𝐫𝐝", "dashboard_main", "danger", icon=6129812419028982717)]
    ]
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

async def show_years_catalog(event):
    msg = (f"<blockquote expandable><tg-emoji emoji-id=\"5409320020058584473\">🏛️</tg-emoji> <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐘𝐞𝐚𝐫 (𝐀𝐠𝐞):</b>\n\n"
           f"<i><tg-emoji emoji-id=\"5408995930416362034\">👑</tg-emoji> 𝐀𝐠𝐞𝐝 𝐚𝐜𝐜𝐨𝐮𝐧𝐭s 𝐡𝐚𝐯𝐞 𝐡𝐢𝐠𝐡𝐞𝐫 𝐭𝐫𝐮𝐬𝐭, 𝐥𝐨𝐰𝐞𝐫 𝐛𝐚𝐧 𝐫𝐚𝐭𝐞𝐬, 𝐚𝐧𝐝 𝐥𝐨𝐧𝐠𝐞𝐫 𝐡𝐢𝐬𝐭𝐨𝐫𝐲!</i></blockquote>")
    btns = []
    for y in [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019]:
        label = YEAR_BADGES.get(y, f"📅 {y}")
        btns.append([style_btn(label, f"c_by_yr|{y}|1", "primary", icon=5408995930416362034)])
    btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)])
    
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

async def _no_stock_card(event, mode=None, country=None, reason=None):
    """Friendly, HONEST empty-state instead of a dead-end or fake stock."""
    country_line = ""
    if country:
        try:
            flag = get_flag_by_country_name(country)
        except Exception:
            flag = "\U0001F30D"
        country_line = f"{flag} <b>{html.escape(str(country))}</b>\n\n"

    reason_line = ""
    if reason:
        reason_line = f"\n\n\u26a0\ufe0f <i>{html.escape(str(reason))}</i>"

    msg = (
        "<blockquote expandable>\U0001F4E6 <b>Stock Update</b>\n\n"
        f"{country_line}"
        "\U0001F533 <b>No live accounts found for this filter right now.</b>\n\n"
        "\u2705 We only show real, currently-available accounts \u2014 no fake "
        "counts. Try another filter, another country, or check back shortly."
        f"{reason_line}</blockquote>"
    )
    btns = [
        [style_btn("\U0001F50D Search Country", "search_country_btn", "primary", icon=5409098988156629257)],
        [style_btn("\u2705 Good Quality Accounts", "pg_c|nonspam|1", "success", icon=5409320020058584473),
         style_btn("\U0001F4B0 Cheap Accounts", "pg_c|spam|1", "primary", icon=5408995930416362034)],
        [style_btn("\U0001F4F1 Basic Telegram Accounts", "mtg_home", "success", icon=5409320020058584473)],
        [style_btn("\U0001F519 Back to Menu", "buy_menu_main", "danger", icon=6129812419028982717)],
    ]
    if isinstance(event, events.CallbackQuery.Event):
        try:
            return await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            return
    return await event.respond(msg, buttons=btns)


async def _lzt_not_configured_card(event, country=None, mode=None):
    """Shown when the LZT market key is missing, so the admin knows why."""
    msg = (
        "<blockquote expandable>\U0001F511 <b>Market Key Missing</b>\n\n"
        "\u26a0\ufe0f The <b>LZT Market API key</b> is not configured, so live "
        "accounts cannot be fetched.\n\n"
        "<b>Admin fix:</b> open the admin panel \u2192 <b>LZT API Key</b> and save "
        "a key with <code>market</code> scope, or set the <code>LZT_API_KEY</code> "
        "environment variable.</blockquote>"
    )
    btns = [
        [style_btn("\U0001F504 Try Again", f"pg_c|{mode or 'bulk'}|1", "primary", icon=5409320020058584473)],
        [style_btn("\U0001F519 Back to Menu", "buy_menu_main", "danger", icon=6129812419028982717)],
    ]
    if isinstance(event, events.CallbackQuery.Event):
        try:
            return await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            return
    return await event.respond(msg, buttons=btns)


async def _lzt_key_invalid_card(event, country=None, mode=None, detail=None):
    """Shown when LZT rejects the stored token (401/403).

    Without this the bot fell back to "No live accounts found", which made an
    expired API token look like an empty market.
    """
    detail_line = ""
    if detail:
        detail_line = (
            "\n\n<i>" + html.escape(str(detail)[:300]) + "</i>"
        )
    msg = (
        "<blockquote expandable>\U0001F511 <b>Market Key Invalid</b>\n\n"
        "\u274c LZT Market rejected the saved <b>API key</b>, so live accounts "
        "cannot be fetched right now.\n\n"
        "<b>Admin fix:</b>\n"
        "1. Open lolz.live \u2192 Account \u2192 API \u2192 "
        "<b>Get Access Token</b>\n"
        "2. Tick the <b>market</b> scope\n"
        "3. Copy the fresh token \u2192 Admin Panel \u2192 "
        "<b>LZT Panel Settings</b> \u2192 <b>Set API Key</b>\n"
        "4. Press <b>Test / Balance</b> to confirm"
        f"{detail_line}</blockquote>"
    )
    btns = [
        [style_btn("\U0001F504 Try Again", f"pg_c|{mode or 'bulk'}|1", "primary",
                   icon=5409320020058584473)],
        [style_btn("\U0001F519 Back to Menu", "buy_menu_main", "danger",
                   icon=6129812419028982717)],
    ]
    if isinstance(event, events.CallbackQuery.Event):
        try:
            return await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            return
    return await event.respond(msg, buttons=btns)


async def show_countries_for_year(event, year, page):
    limit = 10
    offset = (page - 1) * limit
    countries_all = await get_countries_list()
    total = len(countries_all)
    countries = countries_all[offset:offset+limit]
    
    if not countries:
        return await _no_stock_card(event)

    btns = []
    for c_name, count in countries:
        flag = get_flag_by_country_name(c_name)
        price = get_panel_price(c_name, year)
        btns.append(style_btn(f"{flag} {c_name} — {format_dual_from_inr(price)}", f"by|bulk|{c_name}|{year}|{price}", "primary", icon=6154249597532248059))
        
    f_btns = [btns[i:i+2] for i in range(0, len(btns), 2)]
    
    nav = []
    if page > 1: nav.append(style_btn("⬅️ 𝐏𝐫𝐞𝐯", f"c_by_yr|{year}|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total: nav.append(style_btn("𝐍𝐞𝐱𝐭 ➡️", f"c_by_yr|{year}|{page+1}", "primary", icon=6129732880529628243))
    if nav: f_btns.append(nav)
    f_btns.append([style_btn("\U0001F50D Search Country", "search_country_btn",
                              "primary", icon=5409098988156629257)])
    
    f_btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐘𝐞𝐚𝐫𝐬", "by_years_menu", "danger", icon=6129812419028982717)])
    
    total_pages = max(1, (total + limit - 1) // limit)
    msg = f"<blockquote expandable><tg-emoji emoji-id=\"5409320020058584473\">🏛️</tg-emoji> <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 𝐟𝐨𝐫 {year} 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬:</b> (𝐏𝐚𝐠𝐞 {page}/{total_pages})</blockquote>"
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=f_btns)
        except MessageNotModifiedError: pass
    else: await event.respond(msg, buttons=f_btns)

async def show_countries(event, mode, page):
    limit = 12
    offset = (page - 1) * limit
    countries_all = await get_countries_list()
    total = len(countries_all)
    countries = countries_all[offset:offset+limit]
    
    if not countries:
        return await _no_stock_card(event)

    btns = []
    for c_name, count in countries:
        flag = get_flag_by_country_name(c_name)
        cnt_str = f"({count})" if count else ("(0)" if _ss_show_zero() else "")
        btns.append(style_btn(f"{flag} {c_name} {cnt_str}".strip(), f"bc|{mode}|{c_name}", "primary", icon=6154249597532248059))
        
    f_btns = [btns[i:i+2] for i in range(0, len(btns), 2)]
    
    nav = []
    if page > 1: nav.append(style_btn("⬅️ 𝐏𝐫𝐞𝐯", f"pg_c|{mode}|{page-1}", "primary", icon=6129627894349045589))
    nav.append(style_btn("🔍 𝐒𝐞𝐚𝐫𝐜𝐡", "search_country_btn", "primary", icon=5409098988156629257))
    if offset + limit < total: nav.append(style_btn("𝐍𝐞𝐱𝐭 ➡️", f"pg_c|{mode}|{page+1}", "primary", icon=6129732880529628243))
    if nav: f_btns.append(nav)
    
    back_row = []
    if mode != 'bulk':
        back_row.append(style_btn("🎯 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐅𝐢𝐥𝐭𝐞𝐫𝐬", "pg_filters|1", "primary", icon=5409320020058584473))
    back_row.append(style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717))
    f_btns.append(back_row)
    
    total_pages = max(1, (total + limit - 1) // limit)
    if mode in FILTER_BADGES and mode != 'bulk':
        cat_header = f"🎯 <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ({FILTER_BADGES[mode]}):</b>"
    else:
        cat_header = f"📍 <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐚 𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b>"

    msg = f"<blockquote expandable>{cat_header} (𝐏𝐚𝐠𝐞 {page}/{total_pages})</blockquote>"
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=f_btns)
        except MessageNotModifiedError: pass
    else: await event.respond(msg, buttons=f_btns)

async def show_years(event, mode, country):
    if "|" in country:
        parts = country.split("|")
        country = parts[-1].strip()
        if len(parts) > 1 and mode == 'bulk':
            mode = parts[0].strip()
            
    year_options = []

    # Local (manually uploaded) stock is always considered.
    if mode == 'spam':
        rows = cur.execute("SELECT account_year, COUNT(*), price FROM stock WHERE country_name=? AND available=1 AND LOWER(category)='spam' GROUP BY account_year, price", (country,)).fetchall()
    elif mode == 'nonspam':
        rows = cur.execute("SELECT account_year, COUNT(*), price FROM stock WHERE country_name=? AND available=1 AND LOWER(category)!='spam' AND category IS NOT NULL GROUP BY account_year, price", (country,)).fetchall()
    elif mode == 'no_2fa':
        rows = cur.execute("SELECT account_year, COUNT(*), price FROM stock WHERE country_name=? AND available=1 AND (twofa='None' OR twofa IS NULL OR twofa='') GROUP BY account_year, price", (country,)).fetchall()
    elif mode == 'with_2fa':
        rows = cur.execute("SELECT account_year, COUNT(*), price FROM stock WHERE country_name=? AND available=1 AND (twofa!='None' AND twofa IS NOT NULL AND twofa!='') GROUP BY account_year, price", (country,)).fetchall()
    else:
        rows = cur.execute("SELECT account_year, COUNT(*), price FROM stock WHERE country_name=? AND available=1 GROUP BY account_year, price", (country,)).fetchall()

    for y, count, price in rows:
        year_options.append({
            'year': y, 'count': count, 'price': price, 'source': 'local'
        })

    lzt_used = False
    # LIVE LZT search always runs when a market key exists.  Previously this
    # was skipped entirely in 'manual' mode, which is why searching a country
    # that clearly had stock on lzt.market returned "No live accounts found".
    if _lzt_live():
        lzt_used = True
        try:
            items = await lzt_client.search_items(
                country, mode=mode, limit=_ss_int("max_results", 50)
            )
            years_grouped = {}
            for itm in items:
                y = itm['year']
                if y not in years_grouped:
                    price = get_panel_price(country, y, itm['price_rub'], mode=mode)
                    years_grouped[y] = {'count': 0, 'price': price}
                years_grouped[y]['count'] += 1

            for y, info in sorted(years_grouped.items(), key=lambda x: x[0], reverse=True):
                year_options.append({
                    'year': y, 'count': info['count'], 'price': info['price'], 'source': 'lzt'
                })
        except Exception as e:
            # Surface the real reason on the empty-state card instead of a
            # generic "no stock" message (this is how a missing balance
            # attribute used to look like an empty market).
            logger.error(f"Error fetching LZT years for {country}: {e}")
            try:
                lzt_client.last_error = f"LZT search failed: {e}"
            except Exception:
                pass

    if not year_options:
        # Be honest: never fabricate "40+" stock.  If the live panel returned
        # nothing (or LZT is not configured) show a clear empty-state card.
        if not _lzt_live():
            return await _lzt_not_configured_card(event, country, mode)
        reason = getattr(lzt_client, "last_error", None)
        # An expired / wrong-scope token must never look like an empty market.
        status = getattr(lzt_client, "last_status", None)
        if status in (401, 403) or (
            reason and "rejected the API key" in str(reason)
        ):
            return await _lzt_key_invalid_card(event, country, mode, reason)
        return await _no_stock_card(event, mode, country=country, reason=reason)
    
    flag = get_flag_by_country_name(country)
    btns = []
    for opt in year_options:
        y, count, price = opt['year'], opt['count'], opt['price']
        badge = YEAR_BADGES.get(int(y) if str(y).isdigit() else y, f"📅 {y}")
        cnt_text = f"({count} left)" if isinstance(count, int) else f"({count})"
        btns.append([style_btn(f"{badge} — {format_dual_from_inr(price)} {cnt_text}", f"by|{mode}|{country}|{y}|{price}", "primary", icon=5408995930416362034)])
    
    if mode != 'bulk':
        btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬", f"pg_c|{mode}|1", "danger", icon=6129812419028982717)])
    else:
        btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬", "pg_c|bulk|1", "danger", icon=6129812419028982717)])
    
    if mode in FILTER_BADGES and mode != 'bulk':
        cat_label = f" ({FILTER_BADGES[mode]})"
    else:
        cat_label = ""
    
    await event.edit(f"<blockquote expandable>{flag} <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐘𝐞𝐚𝐫 & 𝐏𝐫𝐢𝐜𝐞 𝐟𝐨𝐫 {country}{cat_label}:</b></blockquote>", buttons=btns)

async def _live_stock_count(country, year, mode):
    """Live stock for a country/year, from local DB first then the panel."""
    count = 0
    try:
        rows = cur.execute(
            "SELECT COUNT(*) FROM stock WHERE country_name=? AND available=1",
            (country,),
        ).fetchone()
        count = int(rows[0]) if rows and rows[0] is not None else 0
    except Exception:
        count = 0

    if count == 0 and _lzt_live():
        try:
            items = await lzt_client.search_items(
                country, year=year, mode=mode, limit=_ss_int("max_results", 50)
            )
            count = len(items)
        except Exception as exc:
            logger.debug(f"live stock lookup failed for {country}: {exc}")
    return count


async def confirm_purchase(event, mode, country, year, price):
    if "|" in country:
        parts = country.split("|")
        country = parts[-1].strip()
        if len(parts) > 1 and mode == 'bulk':
            mode = parts[0].strip()
            
    flag = get_flag_by_country_name(country)
    badge = YEAR_BADGES.get(int(year) if str(year).isdigit() else year, f"📅 {year}")
    
    if mode == 'nonspam': cat_badge = "🟢 𝐍𝐨𝐧-𝐒𝐩𝐚𝐦 (𝟏𝟎𝟎% 𝐂𝐥𝐞𝐚𝐧)"
    elif mode == 'spam': cat_badge = "🟡 𝐒𝐩𝐚𝐦 / 𝐔𝐬𝐞𝐝 (𝐂𝐡𝐞𝐚𝐩)"
    else: cat_badge = "🌍 𝐒𝐭𝐚𝐧𝐝𝐚𝐫𝐝"

    # LIVE stock details fetched before the user can buy anything.
    stock_count = await _live_stock_count(country, year, mode)
    msg = stock_card.details_message(
        title="Telegram Account \u2014 Stock Details",
        country_label=f"{flag} <b>{html.escape(str(country))}</b>",
        stock_text=(stock_card.stock_text(stock_count, "accounts")
                    if stock_count else "\U0001F7E2 In stock (live count not reported)"),
        rate_text=format_dual_from_inr(price),
        kind=stock_card.KIND_TG,
        extra_block=(f"{cat_badge}\n\U0001F4C6 <b>Year:</b> {badge}"),
    )
    btns = [
        [style_btn("✅ 𝐂𝐨𝐧𝐟𝐢𝐫𝐦 𝐁𝐮𝐲", f"buy_cf|{mode}|{country}|{year}|{price}", "success", icon=5409320020058584473)],
        [style_btn("❌ 𝐂𝐚𝐧𝐜𝐞𝐥", "cancel_action", "danger", icon=6129888444245089008)]
    ]
    await event.edit(msg, buttons=btns)

async def process_purchase(event, mode, country, year, price_str):
    if "|" in country:
        parts = country.split("|")
        country = parts[-1].strip()
        if len(parts) > 1 and mode == 'bulk':
            mode = parts[0].strip()
            
    uid, price = event.sender_id, int(price_str)
    
    async with get_user_lock(uid):
        disc_row = cur.execute("SELECT discount, balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not disc_row: return await event.answer("❌ User not found!", alert=True)
        discount, balance = disc_row[0], disc_row[1]
        final_price = price if discount == 0 else int(price * (100 - discount) / 100)
        
        if balance < final_price:
            return await event.answer("❌ Insufficient Balance!", alert=True)

        local_row = None
        # Local stock is always checked first; if there is none we fall back to
        # a live LZT purchase.  This must not depend on BOT_MODE, otherwise a
        # 'manual' bot refuses every live purchase with "Out of stock".
        if mode == 'spam':
            local_row = cur.execute("SELECT phone, session_file, twofa FROM stock WHERE country_name=? AND account_year=? AND available=1 AND LOWER(category)='spam' LIMIT 1", (country, int(year))).fetchone()
        elif mode == 'nonspam':
            local_row = cur.execute("SELECT phone, session_file, twofa FROM stock WHERE country_name=? AND account_year=? AND available=1 AND LOWER(category)!='spam' AND category IS NOT NULL LIMIT 1", (country, int(year))).fetchone()
        elif mode == 'no_2fa':
            local_row = cur.execute("SELECT phone, session_file, twofa FROM stock WHERE country_name=? AND available=1 AND (twofa='None' OR twofa IS NULL OR twofa='') LIMIT 1", (country, int(year))).fetchone()
        elif mode == 'with_2fa':
            local_row = cur.execute("SELECT phone, session_file, twofa FROM stock WHERE country_name=? AND available=1 AND (twofa!='None' AND twofa IS NOT NULL AND twofa!='') LIMIT 1", (country, int(year))).fetchone()
        else:
            local_row = cur.execute("SELECT phone, session_file, twofa FROM stock WHERE country_name=? AND account_year=? AND available=1 LIMIT 1", (country, int(year))).fetchone()

        is_local = local_row is not None

        if not is_local and not _lzt_live():
            return await event.answer(
                "\u274c Out of stock! (no local stock and no LZT market key)",
                alert=True,
            )

        if is_local:
            phone, sess, twofa_pass = local_row
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_price, uid, final_price))
            if cur.rowcount == 0: return await event.answer("❌ Insufficient Balance!", alert=True)
            cur.execute("UPDATE stock SET available=0 WHERE phone=?", (phone,))
            db.commit()
        else:
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_price, uid, final_price))
            if cur.rowcount == 0: return await event.answer("❌ Insufficient Balance!", alert=True)
            db.commit()

    c_icon = get_flag_by_country_name(country)
    actual_year = int(year)

    if is_local:
        await event.edit(f"⚡ <b>𝐏𝐫𝐨𝐜𝐞𝐬𝐬𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐨𝐫𝐝𝐞𝐫...</b>\n𝐏𝐥𝐞𝐚𝐬𝐞 𝐰𝐚𝐢𝐭 𝐰𝐡𝐢𝐥𝐞 𝐰𝐞 𝐢𝐧𝐢𝐭𝐢𝐚𝐥𝐢𝐳𝐞 𝐭𝐡𝐞 𝐬𝐞𝐬𝐬𝐢𝐨𝐧.")
        
        client = TelegramClient(sess, API_ID, API_HASH, connection_retries=None, retry_delay=3, auto_reconnect=True)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Session expired or not authorized")
        except Exception as e:
            logger.error(f"Client init error: {e}")
            try: await client.disconnect()
            except Exception: pass
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
                cur.execute("UPDATE stock WHERE phone=?", (phone,))
                db.commit()
            return await event.edit(f"❌ <b>Error initializing account. (Session Dead)</b> Money refunded.")

        temp_order = {'c_icon': c_icon, 'country': country, 'twofa': twofa_pass}
        msg, active_btns = get_active_order_card(temp_order, phone, is_admin(uid))
        sent_msg = await event.edit(msg, buttons=active_btns)
        
        active_orders[phone] = {
            'uid': uid, 'client': client, 'sess': sess, 'start_time': time.time(), 
            'paid': False, 'price': final_price, 'country': country, 'year': actual_year, 
            'c_icon': c_icon, 'twofa': twofa_pass, 'msg_id': sent_msg.id, 'is_lzt': False
        }
        asyncio.create_task(auto_otp_task(phone))
    else:
        await event.edit(f"⚡ <b>𝐏𝐫𝐨𝐜𝐞𝐬𝐬𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐨𝐫𝐝𝐞𝐫...</b>\n𝐏𝐥𝐞𝐚𝐬𝐞 𝐰𝐚𝐢𝐭 𝐰𝐡𝐢𝐥𝐞 𝐰𝐞 𝐢𝐧𝐢𝐭𝐢𝐚𝐥𝐢𝐳𝐞 𝐭𝐡𝐞 𝐬𝐞𝐬𝐬𝐢𝐨𝐧.")
        try:
            items = await lzt_client.search_items(country, actual_year, mode=mode)
            if not items:
                items = await lzt_client.search_items(country, mode=mode)
            
            if not items:
                async with get_user_lock(uid):
                    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
                    db.commit()
                return await event.edit(f"<blockquote expandable>❌ <b>𝐎𝐮𝐭 𝐨𝐟 𝐒𝐭𝐨𝐜𝐤!</b>\n\n𝐍𝐨 𝐚𝐜𝐜𝐨𝐮𝐧𝐭s 𝐚𝐫𝐞 𝐜𝐮𝐫𝐫𝐞𝐧𝐭𝐥𝐲 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐟𝐨𝐫 <b>{c_icon} {country}</b>.\n𝐘𝐨𝐮𝐫 𝐦𝐨𝐧𝐞𝐲 (<b>{format_dual_from_inr(final_price)}</b>) 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 <b>𝐢𝐧𝐬𝐭𝐚𝐧𝐭𝐥𝐲 𝐫𝐞𝐟𝐮𝐧𝐝𝐞𝐝</b>.</blockquote>", buttons=[[style_btn("🛒 𝐁𝐮𝐲 𝐀𝐧𝐨𝐭𝐡𝐞𝐫 𝐂𝐨𝐮𝐧𝐭𝐫𝐲", "buy_menu_main", "primary", icon=5408995930416362034)]])

            buy_success = False
            bought_info = None
            client = None
            phone = None
            last_err = ""

            for itm in items[:5]:
                item_id = itm['item_id']
                price_str = itm.get('price_str', str(itm.get('price_usd', '0.1')))
                balance_id = itm.get('balance_id')
                ok, buy_result = await lzt_client.fast_buy(item_id, price_str, balance_id)
                if ok:
                    bought_data = buy_result.get("item_data") or {}
                    post_sb = bought_data.get("telegram_spam_block")
                    if mode == 'nonspam' and post_sb is not None and post_sb != -1:
                        continue
                    if mode == 'spam' and post_sb == -1:
                        continue

                    str_sess = buy_result.get("string_session")
                    if str_sess:
                        try:
                            from telethon.sessions import StringSession
                            test_client = TelegramClient(StringSession(str_sess), API_ID, API_HASH, connection_retries=None, retry_delay=3, auto_reconnect=True)
                            await test_client.connect()
                            if await test_client.is_user_authorized():
                                me = await test_client.get_me()
                                p = getattr(me, 'phone', None) or buy_result.get("phone") or f"Item-{item_id}"
                                phone = str(p).lstrip('+')
                                client = test_client
                                bought_info = buy_result
                                buy_success = True
                                break
                            else:
                                try: await test_client.disconnect()
                                except Exception: pass
                        except Exception as conn_err:
                            logger.warning(f"Connection error: {conn_err}")
                else:
                    last_err = str(buy_result)

            if not buy_success or not client:
                async with get_user_lock(uid):
                    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
                    db.commit()
                return await event.edit(f"❌ <b>Error initializing account.</b> {last_err or 'Session unavailable.'}\nYour money has been refunded.")

            item_id = bought_info['item_id']
            twofa_pass = bought_info.get("twofa") or "None"
            str_sess = bought_info.get("string_session")

            temp_order = {'c_icon': c_icon, 'country': country, 'twofa': twofa_pass}
            msg, active_btns = get_active_order_card(temp_order, phone, is_admin(uid))
            sent_msg = await event.edit(msg, buttons=active_btns)

            active_orders[phone] = {
                'uid': uid, 'client': client, 'sess': str_sess, 'item_id': item_id,
                'start_time': time.time(), 'paid': False, 'price': final_price,
                'country': country, 'year': actual_year, 'c_icon': c_icon,
                'twofa': twofa_pass, 'msg_id': sent_msg.id, 'is_lzt': True
            }
            asyncio.create_task(auto_otp_task(phone))
        except Exception as e:
            logger.error(f"Purchase flow error: {e}")
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
                db.commit()
            return await event.edit(f"❌ <b>Error initializing account.</b> Money refunded.")

def extract_otp_from_text(text):
    if not text:
        return None
    patterns = [
        r"(?i)(?:login\s*code|web\s*login\s*code|código\s*de\s*inicio\s*de\s*sesión|код\s*подтверждения)[\s:]*([0-9]{5,6})",
        r"(?i)(?:code|kod|kód|código|код)[\s:]*([0-9]{5,6})",
        r"\b([0-9]{5})\b",
        r"\b([0-9]{6})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            code = m.group(1) if m.groups() else m.group(0)
            if code not in {"2024", "2025", "2026", "2027"}:
                return code
    return None

async def fetch_order_otp(order):
    client = order.get('client')
    start_time = order.get('start_time', 0)
    
    if client:
        try:
            if not client.is_connected():
                try: await client.connect()
                except Exception: pass
            
            if client.is_connected():
                msgs = []
                try: msgs = await client.get_messages(777000, limit=5)
                except Exception: pass
                
                for m in msgs:
                    if hasattr(m, 'date') and m.date.timestamp() > start_time - 15:
                        if m.message:
                            code = extract_otp_from_text(m.message)
                            if code: return code
        except Exception as e:
            logger.error(f"Error checking Telegram messages: {e}")

    if order.get('is_lzt') and order.get('item_id'):
        try:
            lzt_code = await lzt_client.get_otp_code(order['item_id'])
            if lzt_code:
                code = extract_otp_from_text(str(lzt_code)) or str(lzt_code).strip()
                if code and re.match(r"^\d{4,8}$", code): return code
        except Exception as lzt_err:
            logger.debug(f"LZT get_otp_code error: {lzt_err}")

    return None

async def auto_otp_task(phone):
    if phone not in active_orders: return
    
    order = active_orders[phone]
    start_time = order['start_time']
    uid = order['uid']
    msg_id = order['msg_id']
    
    while time.time() - start_time < AUTO_CANCEL_SECONDS:
        if phone not in active_orders: return 
        try:
            code = await fetch_order_otp(order)
            
            if code:
                if not order['paid']:
                    order['paid'] = True
                    async with get_user_lock(uid):
                        cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)", (uid, order['country'], order['year'], order['price'], phone, code))
                        if not order.get('is_lzt'):
                            cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
                        db.commit()
                        
                        for log_ch in get_log_channels_db():
                            try:
                                await bot.send_message(log_ch, f"✅ <b>ACCOUNT SOLD</b>\n\n👤 <b>User:</b> <code>{uid}</code>\n📱 <b>Phone:</b> <code>+{phone}</code>\n💰 <b>Price:</b> {format_dual_from_inr(order['price'])}\n🌍 <b>Country:</b> {order['country']}")
                            except Exception as log_ex:
                                logger.error(f"Failed to log sale: {log_ex}")
                
                twofa_text = f"🔐 <b>2FA:</b> <code>{order['twofa']}</code>" if order['twofa'] != "None" else "🔓 <b>2FA:</b> <code>Disabled (No Password)</code>"
                msg_text = (f"<blockquote expandable><tg-emoji emoji-id=\"5409320020058584473\">✅</tg-emoji> <b>𝐎𝐓𝐏 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃!</b> 🔥\n\n"
                            f"📱 <b>𝐏𝐡𝐨𝐧𝐞:</b> <code>+{phone}</code>\n"
                            f"🔑 <b>𝐎𝐓𝐏 𝐂𝐨𝐝𝐞:</b> <code>{code}</code>\n"
                            f"{twofa_text}\n\n"
                            f"<i><tg-emoji emoji-id=\"5408995930416362034\">⚡</tg-emoji> Tap code to copy! Complete login now.</i></blockquote>")
                
                btns = [
                    [
                        style_btn("📥 𝐃𝐨𝐰𝐧𝐥𝐨𝐚𝐝 .𝐒𝐄𝐒𝐒𝐈𝐎𝐍", f"dl_telethon_{phone}", "success", icon=5409320020058584473),
                        style_btn("📥 𝐃𝐨𝐰𝐧𝐥𝐨𝐚𝐝 𝐓𝐃𝐀𝐓𝐀", f"dl_tdata_{phone}", "primary", icon=5408995930416362034)
                    ],
                    [
                        style_btn("📥 Pyrogram / JSON", f"dl_pyrogram_{phone}", "primary", icon=5408995930416362034),
                        style_btn("🔑 𝐐𝐑 𝐋𝐨𝐠𝐢𝐧", f"get_qr_{phone}", "primary", icon=5408995930416362034)
                    ],
                    [
                        style_btn("🔄 𝐆𝐞𝐭 𝐀𝐧𝐨𝐭𝐡𝐞𝐫 𝐎𝐓𝐏", f"get_code_{phone}", "primary", icon=5408995930416362034),
                        style_btn("🚫 𝐓𝐞𝐫𝐦𝐢𝐧𝐚𝐭𝐞 𝐎𝐭𝐡𝐞𝐫 𝐒𝐞𝐬𝐬𝐢𝐨𝐧𝐬", f"reset_sessions_{phone}", "danger", icon=6129888444245089008)
                    ],
                    [style_btn("✅ 𝐅𝐢𝐧𝐢𝐬𝐡 / 𝐃𝐨𝐧𝐞", f"finish_order|{phone}", "success", icon=5409320020058584473)]
                ]
                
                try: await bot.edit_message(uid, msg_id, msg_text, buttons=btns)
                except Exception as ex: logger.error(f"Error updating message: {ex}")
                try:
                    from utils import stickers as _sticker_engine
                    await _sticker_engine.send_purchase(bot, uid, reply_to=msg_id)
                except Exception as _sk_ex:
                    logger.debug(f"purchase emoji skipped: {_sk_ex}")
                return
        except Exception as e:
            logger.error(f"Error in auto_otp_task loop: {e}")
            
        await asyncio.sleep(5)
        
    if phone in active_orders and not active_orders[phone]['paid']:
        ord_info = active_orders[phone]
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (ord_info['price'], uid))
            if not ord_info.get('is_lzt'):
                cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            db.commit()
        
        try:
            client = ord_info.get('client')
            if client: await client.disconnect()
        except Exception: pass
        
        del active_orders[phone]
        
        msg_text = f"<blockquote expandable>❌ <b>𝐎𝐫𝐝𝐞𝐫 𝐓𝐢𝐦𝐞𝐨𝐮𝐭 / 𝐂𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝</b>\n\nNo OTP was received in time. <b>{format_dual_from_inr(ord_info['price'])}</b> has been refunded to your wallet!</blockquote>"
        try: await bot.edit_message(uid, msg_id, msg_text)
        except Exception as e: logger.error(f"Error sending timeout msg: {e}")

async def handle_format_downloads(event, phone, file_type):
    if phone not in active_orders:
        return await event.answer("❌ Session context no longer active. Use order history.", alert=True)
    
    order = active_orders[phone]
    sess = order.get('sess')
    ext = "json" if file_type == "json" else ("session" if file_type in ["telethon", "pyrogram"] else "zip")
    file_path = f"export_{phone}_{file_type}.{ext}"
    
    try:
        await event.answer("⏳ Generating requested session file...", alert=False)
        if file_type == "telethon":
            if isinstance(sess, str) and os.path.exists(sess):
                file_path = sess
            else:
                file_path = f"{phone}.session"
                with open(file_path, "w") as f:
                    f.write(sess or "")
        elif file_type == "json":
            json_data = {"phone": phone, "twofa": order.get("twofa"), "session": sess if isinstance(sess, str) else ""}
            with open(file_path, "w") as f: json.dump(json_data, f, indent=4)
                
        await bot.send_file(event.chat_id, file_path, caption=f"📦 Here is your exported <b>{file_type.upper()}</b> file for <code>+{phone}</code>.")
    except Exception as e:
        logger.error(f"Format download error: {e}")
        await event.answer(f"❌ Failed to generate format: {e}", alert=True)

# ---------------- COMMAND & HANDLER REGISTRATIONS ----------------

@bot.on(events.NewMessage(func=lambda e: e.is_private and matches_menu(e.raw_text, "buy account")))
async def buy_account_handler(event):
    # The reply-keyboard label is rendered with stylised Unicode glyphs
    # ("🛒 𝗕ᴜʏ 𝗔ᴄᴄᴏᴜɴᴛ"), so `matches_menu` folds those back to ASCII
    # before comparing.  Opening the full buy menu (rather than a bare text
    # prompt) makes the button behave exactly like the inline "Buy Account".
    user_states.pop(event.sender_id, None)
    await show_buy_menu(event)
    raise events.StopPropagation

@bot.on(events.CallbackQuery(pattern=b"back_to_menu"))
async def cb_back_to_menu_bytes(event):
    user_id = event.sender_id
    if user_id in user_states:
        del user_states[user_id]
    await safe_edit_message(event, "🏠 Main Menu:", buttons=[
        [style_btn("🛒 Buy Account", "buy_account_cb", "primary")]
    ])

@bot.on(events.CallbackQuery(pattern=r"^buy_account_cb$"))
async def cb_buy_account_cb(event):
    await show_buy_menu(event)

@bot.on(events.CallbackQuery(pattern=r"^search_country_btn$"))
async def cb_search_country_btn(event):
    uid = event.sender_id
    search_state[uid] = True
    user_states[uid] = "AWAITING_COUNTRY"
    msg = "<blockquote expandable>🔍 <b>𝐒𝐞𝐚𝐫𝐜𝐡 𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b>\n\nSend a country name, ISO code or dial code \u2014 e.g. <code>Japan</code>, <code>JP</code>, <code>JPN</code>, <code>+81</code>, <code>India</code>, <code>+91</code>.</blockquote>"
    btns = [[style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)]]
    await event.edit(msg, buttons=btns)

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                          and bool(e.text) and not e.text.startswith("/")))
async def process_combined_text_input(event):
    if not event.text or event.text.startswith("/"):
        return

    uid = event.sender_id

    # Ignore menu triggers so they don't get treated as a country query.
    lowered = event.text.strip().lower()
    if "buy account" in lowered:
        return

    # Let the More Content router handle redeem codes / session strings.
    try:
        from plugins.more_content import more_state as _mc_state
        if _mc_state.get(uid):
            return
    except Exception:
        pass

    if search_state.get(uid) or user_states.get(uid) == "AWAITING_COUNTRY":
        search_state[uid] = False
        user_states[uid] = None

        raw_query = event.text.strip()
        logger.info(f"Country search query from {uid}: {raw_query!r}")

        try:
            countries_all = await get_countries_list()
        except Exception as e:
            logger.error(f"Error fetching country list: {e}")
            countries_all = []

        # Fallback: if no dynamic list is available, search the built-in map.
        if not countries_all:
            countries_all = [(c_name, 0) for c_name, _flag in COUNTRY_CODES.values()]

        matches = search_countries(countries_all, raw_query)

        # Universal fallback: if the panel list did not contain the country,
        # resolve the query (name / ISO-2 / ISO-3 / dial code) anyway so the
        # user still reaches the country and sees an honest "no live stock"
        # card instead of a dead-end "invalid country" error.
        if not matches:
            try:
                from utils.country_search import resolve_country
                resolved = resolve_country(raw_query)
            except Exception:
                resolved = None
            if resolved:
                matches = [(resolved["name"], 0)]
            else:
                return await event.respond(
                    f"\u274c No country found matching '<code>{html.escape(event.text)}</code>'.\n\n"
                    "Try a country name (<code>Japan</code>), a 2-letter code "
                    "(<code>JP</code>), a 3-letter code (<code>JPN</code>) or a "
                    "dial code (<code>+81</code>).",
                    buttons=[[style_btn("\U0001F50D Search Again", "search_country_btn", "primary", icon=5409098988156629257)],
                             [style_btn("\U0001F519 Back to Menu", "buy_menu_main", "danger", icon=6129812419028982717)]],
                )

        btns = []
        for c_name, count in matches[:10]:
            flag = get_flag_by_country_name(c_name)
            cnt_str = f"({count})" if count else ("(0)" if _ss_show_zero() else "")
            btns.append([style_btn(f"{flag} {c_name} {cnt_str}".strip(), f"bc|bulk|{c_name}", "primary", icon=6154249597532248059)])
            
        btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)])
        await event.respond(
            f"<blockquote expandable>🔎 <b>𝐒𝐞𝐚𝐫𝐜𝐡 𝐑𝐞𝐬𝐮𝐥𝐭𝐬 𝐟𝐨𝐫 '{html.escape(event.text)}':</b>\n\n"
            f"✅ <b>Good Quality and Cheap Rates</b> — all accounts below are verified "
            f"and priced at the lowest market rate.</blockquote>",
            buttons=btns,
        )

@bot.on(events.CallbackQuery(pattern=r"^open_buy_categories$"))
async def cb_open_buy_categories(event):
    await show_buy_menu(event)

@bot.on(events.CallbackQuery(pattern=r"^buy_menu_main$"))
async def cb_buy_menu_main(event):
    await show_buy_menu(event)

@bot.on(events.CallbackQuery(pattern=r"^by_years_menu$"))
async def cb_by_years_menu(event):
    await show_years_catalog(event)

@bot.on(events.CallbackQuery(pattern=r"^pg_filters\|(\d+)"))
async def cb_pg_filters(event):
    raw = event.pattern_match.group(1)
    page = int(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    await show_filters_catalog(event, page)

@bot.on(events.CallbackQuery(pattern=r"^c_by_yr\|(\d+)\|(\d+)"))
async def cb_c_by_yr(event):
    r1 = event.pattern_match.group(1)
    r2 = event.pattern_match.group(2)
    year = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    page = int(r2.decode('utf-8') if isinstance(r2, bytes) else r2)
    await show_countries_for_year(event, year, page)

@bot.on(events.CallbackQuery(pattern=r"^pg_c\|([^|]+)\|(\d+)"))
async def cb_pg_c(event):
    r1 = event.pattern_match.group(1)
    r2 = event.pattern_match.group(2)
    mode = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    page = int(r2.decode('utf-8') if isinstance(r2, bytes) else r2)
    await show_countries(event, mode, page)

@bot.on(events.CallbackQuery(pattern=r"^bc\|([^|]+)\|(.+)"))
async def cb_bc(event):
    r1 = event.pattern_match.group(1)
    r2 = event.pattern_match.group(2)
    mode = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    country = r2.decode('utf-8') if isinstance(r2, bytes) else r2
    await show_years(event, mode, country)

@bot.on(events.CallbackQuery(pattern=r"^by\|([^|]+)\|([^|]+)\|([^|]+)\|(.+)"))
async def cb_by(event):
    r1 = event.pattern_match.group(1)
    r2 = event.pattern_match.group(2)
    r3 = event.pattern_match.group(3)
    r4 = event.pattern_match.group(4)
    mode = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    country = r2.decode('utf-8') if isinstance(r2, bytes) else r2
    year = r3.decode('utf-8') if isinstance(r3, bytes) else r3
    price = r4.decode('utf-8') if isinstance(r4, bytes) else r4
    await confirm_purchase(event, mode, country, year, price)

@bot.on(events.CallbackQuery(pattern=r"^buy_cf\|([^|]+)\|([^|]+)\|([^|]+)\|(.+)"))
async def cb_buy_cf(event):
    r1 = event.pattern_match.group(1)
    r2 = event.pattern_match.group(2)
    r3 = event.pattern_match.group(3)
    r4 = event.pattern_match.group(4)
    mode = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    country = r2.decode('utf-8') if isinstance(r2, bytes) else r2
    year = r3.decode('utf-8') if isinstance(r3, bytes) else r3
    price = r4.decode('utf-8') if isinstance(r4, bytes) else r4
    await process_purchase(event, mode, country, year, price)

@bot.on(events.CallbackQuery(pattern=r"^chg_num\|(.+)"))
async def cb_chg_num(event):
    await event.answer("ℹ️️ Please enter your new phone number in chat to migrate.", alert=True)

@bot.on(events.CallbackQuery(pattern=r"^get_otp_again\|(.+)"))
async def cb_get_otp_again(event):
    r1 = event.pattern_match.group(1)
    phone = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    if phone not in active_orders:
        return await event.answer("❌ Order no longer active.", alert=True)
    code = await fetch_order_otp(active_orders[phone])
    if code: await event.answer(f"🔑 Your OTP is: {code}", alert=True)
    else: await event.answer("⏳ Waiting for OTP...", alert=True)

@bot.on(events.CallbackQuery(pattern=r"^dl_(telethon|tdata|pyrogram|json)_(.+)"))
async def cb_download_format(event):
    r1 = event.pattern_match.group(1)
    r2 = event.pattern_match.group(2)
    file_type = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    phone = r2.decode('utf-8') if isinstance(r2, bytes) else r2
    await handle_format_downloads(event, phone, file_type)

@bot.on(events.CallbackQuery(pattern=r"^get_code_(.+)"))
async def cb_get_code_again(event):
    r1 = event.pattern_match.group(1)
    phone = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    if phone not in active_orders:
        return await event.answer("❌ Order expired or completed.", alert=True)
    order = active_orders[phone]
    code = await fetch_order_otp(order)
    if code: await event.answer(f"🔑 Latest OTP: {code}", alert=True)
    else: await event.answer("⏳ Waiting for new OTP...", alert=True)

@bot.on(events.CallbackQuery(pattern=r"^finish_order\|(.+)"))
async def cb_finish_order(event):
    r1 = event.pattern_match.group(1)
    phone = r1.decode('utf-8') if isinstance(r1, bytes) else r1
    if phone in active_orders:
        ord_info = active_orders[phone]
        try:
            if ord_info.get('client'):
                await ord_info['client'].disconnect()
        except Exception: pass
        del active_orders[phone]
    await event.edit("✅ <b>Order completed successfully! Thank you.</b>")
