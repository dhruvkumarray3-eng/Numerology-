"""All Apps Accounts (OTP) + Buy WhatsApp Account.

Flow:
  All apps acc  -> pick app -> pick country -> buy OTP number -> show OTP
  Buy Wp Acc    -> WhatsApp specific flow (same engine, app=whatsapp)
"""
import html
import asyncio
import difflib
import re
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
from utils.keyboards import style_btn, pe

# Per-app premium icon (custom emoji id).  Falls back to a generic phone icon.
APP_ICONS = {
    "telegram": 5408995930416362034,
    "whatsapp": 5440627033111557670,
    "instagram": 5409271925014801629,
    "facebook": 6154249597532248059,
    "tiktok": 6203982793379154737,
    "twitter": 6129732880529628243,
    "youtube": 5409320020058584473,
    "google": 5409320020058584473,
    "gmail": 5409320020058584473,
    "discord": 6129732880529628243,
    "snapchat": 5409320020058584473,
    "uber": 5409320020058584473,
    "amazon": 5440627033111557670,
}
_DEFAULT_APP_ICON = 5409119256107297715  # phone


def _app_icon(slug):
    return APP_ICONS.get((slug or "").lower(), _DEFAULT_APP_ICON)
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

# uid -> app slug while the user is typing a country search query
aa_search_state = {}
# uid -> True while the user is typing an app search query
aa_appsearch_state = {}


def _search_apps(query):
    """Fuzzy search over the app catalogue (also used by the text router)."""
    q = " ".join(str(query or "").lower().replace("_", " ").split()).lstrip("@")
    if not q:
        return []
    alias = {
        "tg": "telegram", "wa": "whatsapp", "insta": "instagram", "ig": "instagram",
        "fb": "facebook", "x": "twitter", "gmail": "google", "chatgpt": "openai",
        "gpt": "openai", "yt": "youtube", "ninja": "ninja", "ninja app": "ninja",
    }
    if q in alias:
        slug = alias[q]
        return [(s, l) for s, l in APP_CATALOG if s == slug] or [(slug, slug.title())]
    scored = []
    for slug, label in APP_CATALOG:
        s = slug.lower()
        l = re.sub(r"[^\w\s]", " ", label.lower())
        l = " ".join(l.split())
        if q == s or q == l:
            score = 100
        elif l.startswith(q) or s.startswith(q):
            score = 80
        elif q in l or q in s:
            score = 60
        else:
            ratio = max(difflib.SequenceMatcher(None, q, l).ratio(),
                        difflib.SequenceMatcher(None, q.replace(" ", ""), s).ratio())
            score = ratio * 35 if ratio >= 0.62 else 0
        if score > 0:
            scored.append((score, slug, label))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(slug, label) for _s, slug, label in scored]

# Curated 5sim country slugs.  The first 16 are shown as buttons; the whole
# list is used by the country search so any supported country can be found.
_AA_SLUG_ISO = [
    ("russia", "ru"), ("india", "in"), ("indonesia", "id"), ("usa", "us"),
    ("england", "gb"), ("philippines", "ph"), ("vietnam", "vn"),
    ("japan", "jp"), ("china", "cn"), ("germany", "de"), ("france", "fr"),
    ("italy", "it"), ("spain", "es"), ("netherlands", "nl"), ("poland", "pl"),
    ("ukraine", "ua"), ("kazakhstan", "kz"), ("malaysia", "my"),
    ("thailand", "th"), ("turkey", "tr"), ("brazil", "br"), ("mexico", "mx"),
    ("canada", "ca"), ("nigeria", "ng"), ("kenya", "ke"), ("pakistan", "pk"),
    ("bangladesh", "bd"), ("srilanka", "lk"), ("uae", "ae"),
    ("saudiarabia", "sa"), ("egypt", "eg"), ("morocco", "ma"),
    ("argentina", "ar"), ("colombia", "co"), ("peru", "pe"), ("chile", "cl"),
    ("romania", "ro"), ("czech", "cz"), ("sweden", "se"), ("norway", "no"),
    ("denmark", "dk"), ("finland", "fi"), ("portugal", "pt"),
    ("greece", "gr"), ("hungary", "hu"), ("bulgaria", "bg"),
    ("serbia", "rs"), ("croatia", "hr"), ("slovakia", "sk"),
    ("slovenia", "si"), ("lithuania", "lt"), ("latvia", "lv"),
    ("estonia", "ee"), ("belarus", "by"), ("moldova", "md"),
    ("georgia", "ge"), ("armenia", "am"), ("azerbaijan", "az"),
    ("uzbekistan", "uz"), ("kyrgyzstan", "kg"), ("mongolia", "mn"),
    ("nepal", "np"), ("myanmar", "mm"), ("cambodia", "kh"), ("laos", "la"),
    ("singapore", "sg"), ("hongkong", "hk"), ("taiwan", "tw"),
    ("southkorea", "kr"), ("australia", "au"), ("newzealand", "nz"),
    ("southafrica", "za"), ("ghana", "gh"), ("uganda", "ug"),
    ("tanzania", "tz"), ("ethiopia", "et"), ("tunisia", "tn"),
    ("algeria", "dz"), ("iraq", "iq"), ("iran", "ir"), ("israel", "il"),
    ("jordan", "jo"), ("kuwait", "kw"), ("qatar", "qa"), ("bahrain", "bh"),
    ("oman", "om"), ("lebanon", "lb"), ("afghanistan", "af"),
]


def _build_countries():
    out = [("any", "🌍 Any")]
    try:
        from utils.country_search import resolve_country
    except Exception:
        resolve_country = None
    for _slug, iso2 in _AA_SLUG_ISO:
        info = resolve_country(iso2) if resolve_country else None
        if info:
            # Key by ISO-2, not the slug: the provider (TemporaSMS/5SIM) and
            # the buy flow both speak ISO codes, and slugs like "england" or
            # "srilanka" never matched the provider's country rows.
            out.append((iso2, f"{info['flag']} {info['name']}"))
        else:
            out.append((iso2, _slug.title()))
    return out


COUNTRIES = _build_countries()
COUNTRIES_VISIBLE = 16


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
        return "⚠️ <b>No OTP provider configured.</b> Add <code>TEMPORASMS_API_KEY</code> (or <code>FIVESIM_API_KEY</code>) in your host variables."
    return "✅ <b>Providers:</b> " + ", ".join(p.upper() for p in provs)


async def show_all_apps(event):
    otp_state.pop(event.sender_id, None)
    btns = []
    row = []
    for slug, label in APP_CATALOG:
        row.append(style_btn(_ensure_emoji(label), f"aa_app|{slug}", "primary", icon=_app_icon(slug)))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    btns.append([style_btn("🔍 Search App", b"aa_appsearch", "primary", icon=5409098988156629257)])
    btns.append([style_btn("🔙 Back", b"buy_menu_main", "danger", icon=6129812419028982717)])

    msg = (
        f"<blockquote expandable>{PE_GIFT} <b>{pe('apps', '📱')} All Apps Accounts (OTP)</b>\n\n"
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
    for iso, label in COUNTRIES[:COUNTRIES_VISIBLE]:
        row.append(style_btn(label, f"aa_c|{app_slug}|{iso}", "primary", icon=_app_icon(app_slug)))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    btns.append([
        style_btn("🔍 Search Country", f"aa_search|{app_slug}", "primary",
                  icon=5409098988156629257),
    ])
    btns.append([style_btn("🔙 Back", b"all_apps_menu", "danger", icon=6129812419028982717)])

    msg = (
        f"<blockquote expandable>{PE_LOCATION} <b>{pe('globe', '🌍')} {html.escape(app_label)} — Select Country</b>\n\n"
        f"{_providers_line()}\n\n"
        f"<i>Pick the country for the number you want, or tap Search Country "
        f"and type a name / ISO code / dial code (e.g. Japan, JP, JPN, +81).</i></blockquote>"
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
    # NEVER expose the raw panel cost.  The only price the buyer sees is
    # panel cost + owner margin, presented as one all-inclusive total.
    total_text = None
    if price is not None:
        try:
            from utils.markup import price_breakdown, format_dual_from_inr
            bd = price_breakdown(price * 100.0)
            total_text = format_dual_from_inr(bd["inr"])
        except Exception as _pb_ex:
            logger.debug(f"price breakdown failed: {_pb_ex}")
    rate_text = total_text or "\U0001F7E1 Live rate unavailable \u2014 tap Refresh"

    extra_block = f"{_ensure_emoji(app_label)} <b>App:</b> {html.escape(app_label)}"
    if total_text:
        extra_block += (
            f"\n\U0001F4B0 <b>Your total price:</b> "
            f"{total_text} <i>(all-inclusive)</i>"
        )
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
            "⚠️ No OTP provider configured. Set TEMPORASMS_API_KEY in host variables.",
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
    # Plain flag emoji is already shown in the details card.  We deliberately
    # do NOT send a premium country-flag emoji before purchase.


def register_all_apps(bot):
    @bot.on(events.CallbackQuery(pattern=r"^all_apps_menu$"))
    async def cb_all_apps(e):
        await show_all_apps(e)

    @bot.on(events.CallbackQuery(pattern=r"^aa_appsearch$"))
    async def cb_aa_appsearch(e):
        aa_appsearch_state[e.sender_id] = True
        aa_search_state.pop(e.sender_id, None)
        msg = (
            "<blockquote expandable>🔍 <b>Search App — All Apps OTP</b>\n\n"
            "Send the app name — e.g. <code>telegram</code>, <code>whatsapp</code>, "
            "<code>instagram</code>, <code>chatgpt</code>, <code>ninja app</code>.\n\n"
            "<i>Any app name works — if it is not in the list we will query the "
            "provider directly.</i></blockquote>"
        )
        btns = [[style_btn("🔙 Back", b"all_apps_menu", "danger", icon=6129812419028982717)]]
        try:
            await e.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^aa_search\|(\w+)$"))
    async def cb_aa_search(e):
        raw = e.pattern_match.group(1)
        slug = raw.decode() if isinstance(raw, bytes) else raw
        aa_search_state[e.sender_id] = slug
        app_label = dict(APP_CATALOG).get(slug, slug)
        msg = (
            f"<blockquote expandable>🔍 <b>Search Country — {html.escape(app_label)}</b>\n\n"
            "Send a country name, ISO code or dial code — e.g. <code>Japan</code>, "
            "<code>JP</code>, <code>JPN</code>, <code>+81</code>, <code>India</code>, "
            "<code>+91</code>.</blockquote>"
        )
        btns = [[style_btn("🔙 Back", f"aa_app|{slug}", "danger",
                           icon=6129812419028982717)]]
        try:
            await e.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass

    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out
                              and bool(e.text) and not e.text.startswith("/")))
    async def aa_text_router(e):
        uid = e.sender_id
        # ---- app search (typed an app name) ----
        if aa_appsearch_state.pop(uid, None):
            query = (e.text or "").strip()
            matches = _search_apps(query)
            if len(matches) == 1:
                await show_countries_for_app(e, matches[0][0])
                raise events.StopPropagation
            if len(matches) > 1:
                btns, row = [], []
                for slug, label in matches[:12]:
                    row.append(style_btn(_ensure_emoji(label)[:60], f"aa_app|{slug}",
                                         "primary", icon=_app_icon(slug)))
                    if len(row) == 2:
                        btns.append(row); row = []
                if row:
                    btns.append(row)
                btns.append([style_btn("🔍 Search Again", b"aa_appsearch", "primary",
                                       icon=5409098988156629257)])
                btns.append([style_btn("🔙 Back", b"all_apps_menu", "danger",
                                       icon=6129812419028982717)])
                msg = (f"<blockquote expandable>🔍 <b>Results for</b> "
                       f"<b>{html.escape(query)}</b>\n\nPick the app you want.</blockquote>")
                await e.respond(msg, buttons=btns)
                raise events.StopPropagation
            # No local match -> let the provider decide (e.g. "ninja app").
            custom = re.sub(r"\b(app|application|account|accounts)\b", " ", query.lower())
            custom = re.sub(r"[^a-z0-9]", "", custom)
            if custom:
                await show_countries_for_app(e, custom)
                raise events.StopPropagation
            await e.respond(
                f"<blockquote>😕 No app matched <b>{html.escape(query)}</b>.\n"
                "Try another name.</blockquote>",
                buttons=[[style_btn("🔍 Search Again", b"aa_appsearch", "primary",
                                    icon=5409098988156629257)],
                         [style_btn("🔙 Back", b"all_apps_menu", "danger",
                                    icon=6129812419028982717)]],
            )
            raise events.StopPropagation

        slug = aa_search_state.get(uid)
        if not slug:
            return
        aa_search_state.pop(uid, None)
        # Mutual exclusion: a pending panel / buy search must not also fire
        # for this same message (avoids duplicate replies).
        try:
            from plugins.product_panels import panel_state as _pp_state
            if _pp_state.get(uid):
                _pp_state[uid]["mode"] = None
        except Exception:
            pass
        try:
            from plugins.buy import search_state as _buy_search, user_states as _buy_states
            _buy_search[uid] = False
            if _buy_states.get(uid) == "AWAITING_COUNTRY":
                _buy_states[uid] = None
        except Exception:
            pass
        query = e.text.strip()
        try:
            from utils.country_search import search_country_names, resolve_country
        except Exception:
            search_country_names = None
            resolve_country = None
        labels = [label for _iso, label in COUNTRIES]
        matches = search_country_names(labels, query) if search_country_names else []
        if matches:
            label = matches[0]
            iso = next((i for i, l in COUNTRIES if l == label), None)
            if iso:
                await show_details(e, slug, iso)
                raise events.StopPropagation
        resolved = resolve_country(query) if resolve_country else None
        if resolved:
            # Match by ISO code first (robust), then fall back to the label.
            iso = None
            want = str(resolved.get("iso2") or "").lower()
            for i, l in COUNTRIES:
                if want and i.lower() == want:
                    iso = i
                    break
            if iso is None:
                for i, l in COUNTRIES:
                    if resolved["name"].lower() in l.lower():
                        iso = i
                        break
            if iso:
                await show_details(e, slug, iso)
                raise events.StopPropagation
            app_label = dict(APP_CATALOG).get(slug, slug)
            msg = (
                f"<blockquote expandable>{resolved['flag']} <b>{html.escape(resolved['name'])}</b> "
                f"(<code>{resolved['iso3'] or resolved['iso2'].upper()}</code>) — "
                f"<b>{html.escape(app_label)}</b>\n\n"
                "🟡 <b>This country is not available on the panel right now.</b>\n"
                "The provider returned no numbers for it. Try another country.</blockquote>"
            )
        else:
            msg = (
                f"<blockquote expandable>😕 No country matched "
                f"<b>{html.escape(query)}</b>.\nTry a name (<code>Japan</code>), "
                "ISO code (<code>JP</code> / <code>JPN</code>) or dial code "
                "(<code>+81</code>).</blockquote>"
            )
        btns = [
            [style_btn("🔍 Search Again", f"aa_search|{slug}", "primary",
                       icon=5409098988156629257)],
            [style_btn("🔙 Back", f"aa_app|{slug}", "danger",
                       icon=6129812419028982717)],
        ]
        try:
            await e.respond(msg, buttons=btns)
        except Exception:
            pass
        raise events.StopPropagation

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
