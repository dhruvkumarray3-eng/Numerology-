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
from utils.otp_providers import (
    APP_CATALOG,
    available_providers,
    provider_configured,
    buy_number,
    get_otp,
)

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
        row.append(style_btn(label, f"aa_app|{slug}", "primary"))
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
        await show_countries_for_app(e, "whatsapp")
