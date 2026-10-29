"""Settings screen: per-user currency and language preferences.

Mirrors the Settings screen from the reference app:
  Currency: INR ₹ / USD $ / EUR € / GBP £
  Language: English / Hinglish / हिंदी / Русский / 中文 / العربية
"""
import html
from telethon import events
from telethon.errors import MessageNotModifiedError

from config import (
    CURRENCY_SYMBOLS,
    SUPPORTED_LANGUAGES,
    PE_FLOWER,
)
from database import (
    get_user_currency,
    set_user_currency,
    get_user_language,
    set_user_language,
)
from utils.keyboards import style_btn, pe

CURRENCY_OPTIONS = [
    ("INR", "🇮🇳 INR ₹ + USDT"),
    ("USDT", "💎 USDT only"),
    ("USD", "🇺🇸 USD $"),
    ("EUR", "🇪🇺 EUR €"),
    ("GBP", "🇬🇧 GBP £"),
]

LANGUAGE_OPTIONS = [
    ("en", "🇬🇧 English"),
    ("hinglish", "🇮🇳 Hinglish"),
    ("hi", "🇮🇳 हिंदी"),
    ("ru", "🇷🇺 Русский"),
    ("zh", "🇨🇳 中文"),
    ("ar", "🇸🇦 العربية"),
]


def _currency_label(code):
    return CURRENCY_SYMBOLS.get(code.upper(), "₹")


async def show_settings(event, uid=None):
    uid = uid or event.sender_id
    cur_code = get_user_currency(uid)
    lang_code = get_user_language(uid)
    lang_label = SUPPORTED_LANGUAGES.get(lang_code, "🇬🇧 English")

    msg = (
        f"<blockquote expandable>{PE_FLOWER} <b>⚙️ Settings</b>\n\n"
        f"{pe('money', '💱')} <b>Currency:</b> <code>{cur_code} {_currency_label(cur_code)}</code>\n"
        f"{pe('globe', '🌐')} <b>Language:</b> <code>{html.escape(lang_label)}</code>\n\n"
        f"<i>Prices and balances are shown in your chosen currency. "
        f"Payment screens (UPI / crypto) may still show the amount you actually pay.</i></blockquote>"
    )

    btns = []
    cur_row = []
    for code, label in CURRENCY_OPTIONS:
        mark = "✅ " if code == cur_code else ""
        cur_row.append(style_btn(f"{mark}{label}", f"set_cur|{code}", "success" if code == cur_code else "primary", icon="money"))
        if len(cur_row) == 2:
            btns.append(cur_row)
            cur_row = []
    if cur_row:
        btns.append(cur_row)

    lang_row = []
    for code, label in LANGUAGE_OPTIONS:
        mark = "✅ " if code == lang_code else ""
        lang_row.append(style_btn(f"{mark}{label}", f"set_lang|{code}", "success" if code == lang_code else "primary", icon="globe"))
        if len(lang_row) == 2:
            btns.append(lang_row)
            lang_row = []
    if lang_row:
        btns.append(lang_row)

    btns.append([style_btn("🔙 Back", b"dashboard_main", "danger", icon=6129812419028982717)])

    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)


def register_settings(bot):
    @bot.on(events.CallbackQuery(pattern=r"^settings_menu$"))
    async def cb_settings_menu(e):
        await show_settings(e)

    @bot.on(events.CallbackQuery(pattern=r"^set_cur\|([A-Za-z]+)$"))
    async def cb_set_currency(e):
        raw = e.pattern_match.group(1)
        code = raw.decode() if isinstance(raw, bytes) else raw
        code = code.upper()
        if code not in CURRENCY_SYMBOLS:
            return await e.answer("❌ Unsupported currency.", alert=True)
        set_user_currency(e.sender_id, code)
        await e.answer(f"✅ Currency set to {code} {_currency_label(code)}", alert=True)
        await show_settings(e)

    @bot.on(events.CallbackQuery(pattern=r"^set_lang\|([A-Za-z]+)$"))
    async def cb_set_language(e):
        raw = e.pattern_match.group(1)
        code = raw.decode() if isinstance(raw, bytes) else raw
        code = code.lower()
        if code not in SUPPORTED_LANGUAGES:
            return await e.answer("❌ Unsupported language.", alert=True)
        set_user_language(e.sender_id, code)
        await e.answer(f"✅ Language set to {SUPPORTED_LANGUAGES[code]}", alert=True)
        await show_settings(e)
