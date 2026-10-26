"""All Apps Accounts (OTP) + Buy WhatsApp Account.

Flow:
  All apps acc  -> pick app -> pick country -> buy OTP number -> show OTP
  Buy Wp Acc    -> WhatsApp specific flow (same engine, app=whatsapp)
"""
import html
import asyncio
from telethon import events, Button
from telethon.errors import MessageNotModifiedError

from config import (
    PE_GIFT,
    PE_CHECK,
    PE_LIGHTNING,
    PE_LOCATION,
    P_INR,
    logger,
)
from database import cur, db, get_user_currency, update_balance
from utils.keyboards import style_btn
from utils import stickers as sticker_engine
from utils.otp_providers import (
    APP_CATALOG,
    available_providers,
    provider_configured,
    buy_number,
    get_otp,
    get_stock,
)
from utils import stock_details as stock_card

# uid -> {"app": slug, "country": iso, "order_id":..., "provider":...}
otp_state = {}

COUNTRIES = [
    ("any", "🌍 Any"),
    ("russia", "🇷🇺 Russia"),
    ("india", "🇮🇳 India"),
    ("indonesia", "🇮🇩 Indonesia"),
    ("usa", "🇺🇸 USA"),
    ("england", "🇬🇧 UK"),
    ("philippines", "🇵🇭 Philippines"),
    ("vietnam", "🇻🇳 Vietnam"),
]


_EMOJI_FALLBACK = "📱"


def _has_emoji(text):
    if not text:
        return False
    code = ord(text.strip()[0])
    return (0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF
            or 0x2190 <= code <= 0x21FF or 0x2B00 <= code <= 0x2BFF
            or code in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139))


def _ensure_emoji(label):
    label = (label or "").strip()
    if not label:
        return _EMOJI_FALLBACK
    return label if _has_emoji(label) else f"{_EMOJI_FALLBACK} {label}"


def _providers_line():
    provs = available_providers()
    if not provs:
        return "⚠️ <b>No OTP provider configured.</b> Add <code>FIVESIM_API_KEY</code> (or another provider key) in your host variables."
    return "✅ <b>Providers:</b> " + ", ".join(p.upper() for p in provs)


async def show_all_apps(event):
    otp_state.pop(event.sender_id, None)
    btns = []
    row = []
    for slug, label in APP_CATALOG:
        row.append(style_btn(_ensure_emoji(label), f"aa_app|{slug}", "primary"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    btns.append([style_btn("🔙 Back", b"buy_menu_main", "danger", icon=6129812419028982717)])

    msg = (
        f"<blockquote expandable>{PE_GIFT} <b>📱 All Apps Accounts (OTP)</b>\n\n"
        f"Buy a verified OTP number for any app — Telegram, WhatsApp, Instagram, "
        f"Facebook, TikTok and more.\n\n"
        f"{_providers_line()}\n\n"
        f"<i>Select an app to see live prices.</i></blockquote>"
    )
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)


async def show_countries_for_app(event, app_slug):
    otp_state[event.sender_id] = {"app": app_slug}
    app_label = dict(APP_CATALOG).get(app_slug, app_slug)
    btns = []
    row = []
    for iso, label in COUNTRIES:
        row.append(style_btn(label, f"aa_c|{app_slug}|{iso}", "primary"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    btns.append([style_btn("🔙 Back", b"all_apps_menu", "danger", icon=6129812419028982717)])

    msg = (
        f"<blockquote expandable>{PE_LOCATION} <b>{html.escape(app_label)} — Select Country</b>\n\n"
        f"{_providers_line()}\n\n"
        f"<i>Pick the country for the number you want.</i></blockquote>"
    )
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(msg, buttons=btns)

    # Premium custom-emoji logic: send the app logo from the apps pack.
    try:
        await sticker_engine.send_for_event(event, app_label, role="apps")
    except Exception as _sk_ex:
        logger.debug(f"premium app emoji skipped: {_sk_ex}")


async def show_details(event, app_slug, country_iso):
    """Country tapped -> LIVE stock details (stock + rate + quality), not a buy."""
    app_label = dict(APP_CATALOG).get(app_slug, app_slug)
    country_label = dict(COUNTRIES).get(country_iso, country_iso.upper())
    await event.answer("\u23f3 Fetching live stock\u2026")

    count, price, provider = await get_stock(app_slug, country_iso)
    if price is not None:
        rate_text = f"\u20b9{price * 100:.2f} (panel cost) \u00b7 {provider.upper()}"
    else:
        rate_text = "\U0001F7E1 Live rate unavailable \u2014 tap Refresh"

    extra_block = f"{_ensure_emoji(app_label)} <b>App:</b> {html.escape(app_label)}"
    if not provider_configured():
        extra_block += "\n\u26a0\ufe0f <i>No OTP provider configured on the host.</i>"

    msg = stock_card.details_message(
        title=f"{app_label} \u2014 Stock Details",
        country_label=f"{country_label}",
        stock_text=stock_card.stock_text(count, "numbers"),
        rate_text=rate_text,
        kind=stock_card.KIND_OTP,
        extra_block=extra_block,
    )
    btns = [
        [style_btn("\u2705 Buy Now", f"aa_confirm|{app_slug}|{country_iso}", "success",
                   icon=5409320020058584473)],
        [style_btn("\U0001F504 Refresh Stock", f"aa_c|{app_slug}|{country_iso}", "primary",
                   icon=5409320020058584473),
         style_btn("\U0001F519 Back", b"all_apps_menu", "danger",
                   icon=6129812419028982717)],
    ]
    try:
        await event.edit(msg, buttons=btns)
    except MessageNotModifiedError:
        pass

    try:
        await sticker_engine.send_for_event(event, app_label, role="apps")
    except Exception as _sk_ex:
        logger.debug(f"premium app emoji skipped: {_sk_ex}")


async def do_buy(event, app_slug, country_iso):
    uid = event.sender_id
    if not provider_configured():
        return await event.answer(
            "⚠️ No OTP provider configured. Set FIVESIM_API_KEY in host variables.",
            alert=True,
        )
    await event.answer("⏳ Requesting number...")
    result = await buy_number(app_slug, country_iso)
    if not result.get("ok"):
        return await event.edit(
            f"<blockquote>❌ <b>Could not get a number.</b>\n<code>{html.escape(str(result.get('error')))}</code></blockquote>",
            buttons=[[style_btn("🔙 Back", b"all_apps_menu", "primary")]],
        )
    otp_state[uid] = {
        "app": app_slug,
        "country": country_iso,
        "order_id": result["order_id"],
        "provider": result["provider"],
        "phone": result["phone"],
    }
    app_label = dict(APP_CATALOG).get(app_slug, app_slug)
    msg = (
        f"<blockquote expandable>{PE_CHECK} <b>Number Ready!</b>\n\n"
        f"📱 <b>App:</b> {html.escape(app_label)}\n"
        f"☎️ <b>Number:</b> <code>{html.escape(str(result['phone']))}</code>\n"
        f"🆔 <b>Order:</b> <code>{html.escape(str(result['order_id']))}</code>\n\n"
        f"<i>Use this number to sign up. Then tap <b>Get OTP</b> to fetch the code.</i></blockquote>"
    )
    btns = [
        [style_btn("🔑 Get OTP", b"aa_getotp", "success", icon=5409098988156629257)],
        [style_btn("🔙 Back", b"all_apps_menu", "danger", icon=6129812419028982717)],
    ]
    try:
        await event.edit(msg, buttons=btns)
    except MessageNotModifiedError:
        pass
    await sticker_engine.send_for_event(event, country_iso, mode_required="country")


def register_all_apps(bot):
    @bot.on(events.CallbackQuery(pattern=r"^all_apps_menu$"))
    async def cb_all_apps(e):
        await show_all_apps(e)

    @bot.on(events.CallbackQuery(pattern=r"^aa_app\|(\w+)$"))
    async def cb_aa_app(e):
        raw = e.pattern_match.group(1)
        slug = raw.decode() if isinstance(raw, bytes) else raw
        await show_countries_for_app(e, slug)

    @bot.on(events.CallbackQuery(pattern=r"^aa_c\|(\w+)\|(\w+)$"))
    async def cb_aa_country(e):
        a = e.pattern_match.group(1)
        c = e.pattern_match.group(2)
        app_slug = a.decode() if isinstance(a, bytes) else a
        country = c.decode() if isinstance(c, bytes) else c
        await show_details(e, app_slug, country)

    @bot.on(events.CallbackQuery(pattern=r"^aa_confirm\|(\w+)\|(\w+)$"))
    async def cb_aa_confirm(e):
        a = e.pattern_match.group(1)
        c = e.pattern_match.group(2)
        app_slug = a.decode() if isinstance(a, bytes) else a
        country = c.decode() if isinstance(c, bytes) else c
        await do_buy(e, app_slug, country)

    @bot.on(events.CallbackQuery(pattern=r"^aa_getotp$"))
    async def cb_aa_getotp(e):
        st = otp_state.get(e.sender_id)
        if not st or not st.get("order_id"):
            return await e.answer("❌ No active order. Start again.", alert=True)
        await e.answer("⏳ Checking for OTP...")
        code = await get_otp(st["provider"], st["order_id"])
        if code:
            await e.edit(
                f"<blockquote>{PE_CHECK} <b>OTP Received!</b>\n\n"
                f"☎️ <b>Number:</b> <code>{html.escape(str(st.get('phone')))}</code>\n"
                f"🔑 <b>Code:</b> <code>{html.escape(str(code))}</code></blockquote>",
                buttons=[[style_btn("🔙 Back", b"all_apps_menu", "primary")]],
            )
        else:
            await e.edit(
                f"<blockquote>⏳ <b>No OTP yet.</b> Please wait a few seconds and tap Get OTP again.</blockquote>",
                buttons=[
                    [style_btn("🔑 Get OTP", b"aa_getotp", "success")],
                    [style_btn("🔙 Back", b"all_apps_menu", "danger")],
                ],
            )

    @bot.on(events.CallbackQuery(pattern=r"^buy_wp_acc$"))
    async def cb_buy_wp(e):
        # Dedicated WhatsApp panel (TemporaSMS) with its own T&C + country list.
        from plugins.product_panels import show_terms, show_countries, _terms_accepted
        if not _terms_accepted(e.sender_id, "whatsapp"):
            return await show_terms(e, "whatsapp")
        await show_countries(e, "whatsapp", 1)
