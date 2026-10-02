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
from utils.keyboards import style_btn
from utils.states import active_orders, session_buy_state, get_user_lock
from utils.lzt import lzt_client, COUNTRY_TO_LZT, get_lzt_code

search_state = {}
change_number_state = {}
user_states = {}

# Comprehensive Country & Dial Code Fallback Map
COUNTRY_MAP = {
    "india": "India", "in": "India", "+91": "India", "91": "India",
    "usa": "USA", "us": "USA", "+1": "USA", "1": "USA",
    "south africa": "South Africa", "+27": "South Africa", "27": "South Africa",
    "uk": "UK", "gb": "UK", "+44": "UK", "44": "UK",
    "canada": "Canada", "+1ca": "Canada",
}

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

async def get_countries_list():
    bot_mode = get_bot_mode()
    
    if bot_mode == 'manual':
        rows = cur.execute("SELECT country_name, COUNT(*) FROM stock WHERE available=1 GROUP BY country_name").fetchall()
        return sorted(rows, key=lambda x: x[0])

    if bot_mode == 'panel':
        all_c = set(COUNTRY_TO_LZT.keys())
        try:
            customs = cur.execute("SELECT name FROM custom_countries").fetchall()
            for (c,) in customs: all_c.add(c)
        except Exception: pass
        return sorted([(c_name, '40+') for c_name in all_c], key=lambda x: x[0])

    all_c = set(COUNTRY_TO_LZT.keys())
    try:
        customs = cur.execute("SELECT name FROM custom_countries").fetchall()
        for (c,) in customs: all_c.add(c)
    except Exception: pass
    
    country_dict = {c_name: '40+' for c_name in all_c}
    local_rows = cur.execute("SELECT country_name, COUNT(*) FROM stock WHERE available=1 GROUP BY country_name").fetchall()
    for c_name, count in local_rows:
        country_dict[c_name] = count

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
           f"🟢 <b>𝐍𝐨𝐧-𝐒𝐩𝐚𝐦 / 𝐂𝐥𝐞𝐚𝐧:</b> 100% 𝐒𝐩𝐚𝐦𝐛𝐥𝐨𝐜𝐤-𝐅𝐫𝐞𝐞 (𝐃𝐌 & 𝐏𝐞𝐫𝐬𝐨𝐧𝐚𝐥 𝐔𝐬𝐞).\n"
           f"🟡 <b>𝐒𝐩𝐚𝐦 / 𝐔𝐬𝐞𝐝 (𝐂𝐡𝐞𝐚𝐩):</b> 𝐁𝐮𝐝𝐠𝐞𝐭 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬 (𝐂𝐡𝐚𝐧𝐧𝐞𝐥 𝐉𝐨𝐢𝐧𝐞𝐫𝐬 & 𝐌𝐞𝐦𝐛𝐞𝐫𝐬).\n"
           f"🎯 <b>𝐌𝐨𝐫𝐞 𝐅𝐢𝐥𝐭𝐞𝐫𝐬:</b> 𝐒𝐭𝐚𝐫𝐬, 𝐄𝐦𝐚𝐢𝐥, 2𝐅𝐀, 𝐏𝐫𝐞𝐦𝐢𝐮𝐦, 𝐃𝐂...\n"
           f"🌍 <b>𝐀𝐥𝐥 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬:</b> 𝐁𝐫𝐨𝐰𝐬𝐞 50+ 𝐜𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬 𝐬𝐭𝐨𝐜𝐤 (𝐅𝐫𝐞𝐬𝐡 & 𝐀𝐥𝐥).\n"
           f"🏛 <b>𝐎𝐥𝐝 / 𝐀𝐠𝐞𝐝 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬:</b> 𝐅𝐢𝐥𝐭𝐞𝐫 𝐛𝐲 𝐒𝐩𝐞𝐜𝐢𝐟𝐢𝐜 𝐘𝐞𝐚𝐫 (2025, 2024, 2023...).</blockquote>")
    btns = [
        [style_btn("🔍 𝐒𝐞𝐚𝐫𝐜𝐡 𝐂𝐨𝐮𝐧𝐭𝐫𝐲", "search_country_btn", "primary", icon=5409098988156629257)],
        [
            style_btn("🟢 𝐍𝐨𝐧-𝐒𝐩𝐚𝐦 / 𝐂𝐥𝐞𝐚𝐧", "pg_c|nonspam|1", "success", icon=5409320020058584473),
            style_btn("🟡 𝐒𝐩𝐚𝐦 / 𝐔𝐬𝐞𝐝 (𝐂𝐡𝐞𝐚𝐩)", "pg_c|spam|1", "primary", icon=5408995930416362034)
        ],
        [style_btn("🎯 𝐌𝐨𝐫𝐞 𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐅𝐢𝐥𝐭𝐞𝐫𝐬 (𝐒𝐭𝐚𝐫𝐬/2𝐅𝐀...)", "pg_filters|1", "success", icon=5409320020058584473)],
        [style_btn("🌍 𝐀𝐥𝐥 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬 (𝐅𝐫𝐞𝐬𝐡 & 𝐀𝐥𝐥)", "pg_c|bulk|1", "primary", icon=6154249597532248059)],
        [style_btn("🏛️ 𝐎𝐥𝐝 / 𝐀𝐠𝐞𝐝 𝐀𝐜𝐜𝐨𝐮𝐧𝐭𝐬 (𝐛𝐲 𝐘𝐞𝐚𝐫)", "by_years_menu", "primary", icon=5408995930416362034)],
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

async def show_countries_for_year(event, year, page):
    limit = 10
    offset = (page - 1) * limit
    countries_all = await get_countries_list()
    total = len(countries_all)
    countries = countries_all[offset:offset+limit]
    
    if not countries:
        return await event.respond(f"⚠️ 𝐍𝐨 𝐬𝐭𝐨𝐜𝐤 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐟𝐨𝐫 {year} 𝐚𝐭 𝐭𝐡𝐞 𝐦𝐨𝐦𝐞𝐧𝐭.")

    btns = []
    for c_name, count in countries:
        flag = get_flag_by_country_name(c_name)
        price = get_panel_price(c_name, year)
        btns.append(style_btn(f"{flag} {c_name} — ₹{price}", f"by|bulk|{c_name}|{year}|{price}", "primary", icon=6154249597532248059))
        
    f_btns = [btns[i:i+2] for i in range(0, len(btns), 2)]
    
    nav = []
    if page > 1: nav.append(style_btn("⬅️ 𝐏𝐫𝐞𝐯", f"c_by_yr|{year}|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total: nav.append(style_btn("𝐍𝐞𝐱𝐭 ➡️", f"c_by_yr|{year}|{page+1}", "primary", icon=6129732880529628243))
    if nav: f_btns.append(nav)
    
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
        return await event.respond(f"⚠️ 𝐍𝐨 𝐬𝐭𝐨𝐜𝐤 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐚𝐭 𝐭𝐡𝐞 𝐦𝐨𝐦𝐞𝐧𝐭. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐜𝐡𝐞𝐜𝐤 𝐛𝐚𝐜𝐤 𝐥𝐚𝐭𝐞𝐫!")

    btns = []
    for c_name, count in countries:
        flag = get_flag_by_country_name(c_name)
        cnt_str = f"({count})" if count else "(40+)"
        btns.append(style_btn(f"{flag} {c_name} {cnt_str}", f"bc|{mode}|{c_name}", "primary", icon=6154249597532248059))
        
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
            
    bot_mode = get_bot_mode()
    year_options = []
    
    if bot_mode in ('manual', 'hybrid'):
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

    if (bot_mode == 'panel' or (bot_mode == 'hybrid' and not year_options)) and get_lzt_key():
        try:
            items = await lzt_client.search_items(country, mode=mode, category_name='telegram')
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
            logger.error(f"Error fetching LZT years for {country}: {e}")

    if not year_options:
        for y in [2026, 2025, 2024, 2023, 2022, 2021]:
            year_options.append({
                'year': y, 'count': '40+', 'price': get_panel_price(country, y, mode=mode), 'source': 'lzt'
            })
    
    flag = get_flag_by_country_name(country)
    btns = []
    for opt in year_options:
        y, count, price = opt['year'], opt['count'], opt['price']
        badge = YEAR_BADGES.get(int(y) if str(y).isdigit() else y, f"📅 {y}")
        cnt_text = f"({count} left)" if isinstance(count, int) else f"({count})"
        btns.append([style_btn(f"{badge} — ₹{price} {cnt_text}", f"by|{mode}|{country}|{y}|{price}", "primary", icon=5408995930416362034)])
    
    if mode != 'bulk':
        btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬", f"pg_c|{mode}|1", "danger", icon=6129812419028982717)])
    else:
        btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐂𝐨𝐮𝐧𝐭𝐫𝐢𝐞𝐬", "pg_c|bulk|1", "danger", icon=6129812419028982717)])
    
    if mode in FILTER_BADGES and mode != 'bulk':
        cat_label = f" ({FILTER_BADGES[mode]})"
    else:
        cat_label = ""
    
    await event.edit(f"<blockquote expandable>{flag} <b>𝐒𝐞𝐥𝐞𝐜𝐭 𝐘𝐞𝐚𝐫 & 𝐏𝐫𝐢𝐜𝐞 𝐟𝐨𝐫 {country}{cat_label}:</b></blockquote>", buttons=btns)

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

    msg = (f"<blockquote expandable><tg-emoji emoji-id=\"5408995930416362034\">🎁</tg-emoji> <b>𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄</b> <tg-emoji emoji-id=\"5409320020058584473\">💎</tg-emoji>\n\n"
           f"🏳 <b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b> {flag} {country}\n"
           f"🏷️ <b>𝐂𝐚𝐭𝐞𝐠𝐨𝐫𝐲:</b> {cat_badge}\n"
           f"📆 <b>𝐘𝐞𝐚𝐫:</b> {badge}\n"
           f"💵 <b>𝐏𝐫𝐢𝐜𝐞:</b> ₹{price}\n\n"
           f"<b><tg-emoji emoji-id=\"5409320020058584473\">✨</tg-emoji> 𝐀𝐫𝐞 𝐲𝐨𝐮 𝐬𝐮𝐫𝐞 𝐲𝐨𝐮 𝐰𝐚𝐧𝐭 𝐭𝐨 𝐛𝐮𝐲?</b></blockquote>")
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
    bot_mode = get_bot_mode()
    
    async with get_user_lock(uid):
        disc_row = cur.execute("SELECT discount, balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not disc_row: return await event.answer("❌ User not found!", alert=True)
        discount, balance = disc_row[0], disc_row[1]
        final_price = price if discount == 0 else int(price * (100 - discount) / 100)
        
        if balance < final_price:
            return await event.answer("❌ Insufficient Balance!", alert=True)

        local_row = None
        if bot_mode in ('manual', 'hybrid'):
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
        
        is_local = (bot_mode in ('manual', 'hybrid')) and (local_row is not None)
        
        if not is_local and bot_mode == 'manual':
            return await event.answer("❌ Out of stock!", alert=True)

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
            items = await lzt_client.search_items(country, actual_year, mode=mode, category_name='telegram')
            if not items:
                items = await lzt_client.search_items(country, mode=mode, category_name='telegram')
            
            if not items:
                async with get_user_lock(uid):
                    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
                    db.commit()
                return await event.edit(f"<blockquote expandable>❌ <b>𝐎𝐮𝐭 𝐨𝐟 𝐒𝐭𝐨𝐜𝐤!</b>\n\n𝐍𝐨 𝐚𝐜𝐜𝐨𝐮𝐧𝐭s 𝐚𝐫𝐞 𝐜𝐮𝐫𝐫𝐞𝐧𝐭𝐥𝐲 𝐚𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐟𝐨𝐫 <b>{c_icon} {country}</b>.\n𝐘𝐨𝐮𝐫 𝐦𝐨𝐧𝐞𝐲 (<b>₹{final_price}</b>) 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 <b>𝐢𝐧𝐬𝐭𝐚𝐧𝐭𝐥𝐲 𝐫𝐞𝐟𝐮𝐧𝐝𝐞𝐝</b>.</blockquote>", buttons=[[style_btn("🛒 𝐁𝐮𝐲 𝐀𝐧𝐨𝐭𝐡𝐞𝐫 𝐂𝐨𝐮𝐧𝐭𝐫𝐲", "buy_menu_main", "primary", icon=5408995930416362034)]])

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
                                await bot.send_message(log_ch, f"✅ <b>ACCOUNT SOLD</b>\n\n👤 <b>User:</b> <code>{uid}</code>\n📱 <b>Phone:</b> <code>+{phone}</code>\n💰 <b>Price:</b> ₹{order['price']}\n🌍 <b>Country:</b> {order['country']}")
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
        
        msg_text = f"<blockquote expandable>❌ <b>𝐎𝐫𝐝𝐞𝐫 𝐓𝐢𝐦𝐞𝐨𝐮𝐭 / 𝐂𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝</b>\n\nNo OTP was received in time. <b>₹{ord_info['price']}</b> has been refunded to your wallet!</blockquote>"
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

@bot.on(events.NewMessage(pattern=r"(?i).*(buy account).*"))
async def buy_account_handler(event):
    user_id = event.sender_id
    user_states[user_id] = "AWAITING_COUNTRY"
    
    msg_text = (
        "🔍 <b>Search Country:</b>\n\n"
        "Please type the country name or dial code (e.g., <b>India</b> or <b>+91</b>) in chat below."
    )
    buttons = [[style_btn("❌ ⬅️ Back to Menu", "back_to_menu", "danger")]]
    await event.respond(msg_text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"tc_accept"))
async def cb_tc_accept_bytes(event):
    try:
        logger.info(f"CALLBACK RECEIVED: b'tc_accept' from {event.sender_id}")
        await safe_edit_message(event, "✅ Terms accepted! Select an option below.", buttons=[
            [style_btn("🛒 Buy Account", "buy_account_cb", "primary")]
        ])
    except Exception as e:
        logger.error(f"Unhandled exception in cb_tc_accept: {e}")

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
    msg = "<blockquote expandable>🔍 <b>𝐒𝐞𝐚𝐫𝐜𝐡 𝐂𝐨𝐮𝐧𝐭𝐫𝐲:</b>\n\nPlease type the country name or dial code (e.g., <code>India</code> or <code>+91</code>) in chat below.</blockquote>"
    btns = [[style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)]]
    await event.edit(msg, buttons=btns)

@bot.on(events.NewMessage)
async def process_combined_text_input(event):
    if event.text.startswith("/"):
        return
        
    uid = event.sender_id
    
    if search_state.get(uid) or user_states.get(uid) == "AWAITING_COUNTRY":
        search_state[uid] = False
        user_states[uid] = None
        
        raw_query = event.text.strip().lower()
        clean_query = raw_query.replace("+", "")
        
        # Resolve via mapping or direct match
        query = COUNTRY_MAP.get(raw_query) or COUNTRY_MAP.get(clean_query) or raw_query

                   countries_all = await get_countries_list()
        
        matches = [
            (c, cnt) for c, cnt in countries_all 
            if query in c.lower() or clean_query in str(COUNTRY_CODES.get(c, '')).lower()
        ]
             


        
        if not matches:
            return await event.respond(f"❌ No country found matching '<code>{html.escape(event.text)}</code>'. Please try again with a valid country or code (e.g. India, +91, +1).", buttons=[[style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)]])
            
        btns = []
        for c_name, count in matches[:10]:
            flag = get_flag_by_country_name(c_name)
            cnt_str = f"({count})" if count else "(40+)"
            btns.append([style_btn(f"{flag} {c_name} {cnt_str}", f"bc|bulk|{c_name}", "primary", icon=6154249597532248059)])
            
        btns.append([style_btn("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", "buy_menu_main", "danger", icon=6129812419028982717)])
        await event.respond(f"<blockquote expandable>🔎 <b>𝐒𝐞𝐚𝐫𝐜𝐡 𝐑𝐞𝐬𝐮𝐥𝐭𝐬 𝐟𝐨𝐫 '{html.escape(event.text)}':</b></blockquote>", buttons=btns)

@bot.on(events.CallbackQuery(pattern=r"^open_buy_categories$"))
async def cb_open_buy_categories(event):
    await show_buy_menu(event)

@bot.on(events.CallbackQuery(pattern=r"^tc_accept$"))
async def cb_tc_accept(event):
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

@bot.on(events.CallbackQuery(pattern=r"^cancel_action$"))
async def cb_cancel_action(event):
    await show_buy_menu(event)

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
