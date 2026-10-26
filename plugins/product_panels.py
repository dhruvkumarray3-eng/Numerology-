"""Dedicated product panels — each button runs its own panel.

    💬 WhatsApp Account panel      -> TemporaSMS (service = TEMPORASMS_SERVICE_WHATSAPP)
    🔁 TG Number Change panel      -> TemporaSMS (service = TEMPORASMS_SERVICE_NUMCHANGE)
    🧩 All Apps OTP panel         -> TemporaSMS (service = selected app slug)

Every panel has the exact flow from the reference screenshots:

    T&C screen   -> [How to buy] [Agree & Continue] [Cancel]
    Country list -> 2-per-row buttons with price, pagination, Search Country,
                    Refresh, Back
    Buy          -> order card with phone number, Get OTP, Cancel & Refund

Prices shown to the user ALWAYS come from utils.markup.apply_markup(), so the
panel's real cost is never exposed. Profit can be a percentage or a fixed
amount in INR/USD (see /setmarkup and /setprofit).
"""
import asyncio
import html
import time

from telethon import events
from telethon.errors import MessageNotModifiedError

from config import (
    TEMPORASMS_SERVICE_WHATSAPP,
    TEMPORASMS_SERVICE_NUMCHANGE,
    TEMPORASMS_SERVICE_ALLOTP,
    TEMPORASMS_COUNTRY_WHATSAPP,
    TEMPORASMS_COUNTRY_NUMCHANGE,
    TEMPORASMS_COUNTRY_ALLOTP,
    format_price,
    logger,
)
from database import cur, db, ensure_user, get_user_currency
from utils.keyboards import style_btn, matches_menu
from utils import temporasms
from utils.markup import (
    apply_markup, get_markup_config, describe_markup,
    format_dual_price, format_dual_from_inr, price_breakdown,
)
from utils import mongo_store

PAGE_SIZE = 12
CACHE_TTL = 240

PANELS = {
    "whatsapp": {
        "title": "WhatsApp Account",
        "short": "WhatsApp",
        "icon": "💬",
        "service": TEMPORASMS_SERVICE_WHATSAPP,
        "country": TEMPORASMS_COUNTRY_WHATSAPP,
        "style": "success",
        "tc_title": "WhatsApp Account — Terms & Conditions",
        "tc_body": (
            "These are not ready-made accounts — a fresh new number will be "
            "provided from the panel.\n\n"
            "Sometimes you may get an account on your very first buy, and "
            "sometimes you need to try multiple times. This is not dependent "
            "on us, it's a WhatsApp security system.\n\n"
            "For a better experience and to avoid problems, please read the "
            "guide below. Then click <b>Agree &amp; Continue</b> to proceed."
        ),
        "guide": (
            "<b>How to buy a WhatsApp account</b>\n\n"
            "1️⃣ Pick your country from the list.\n"
            "2️⃣ Tap the country button — a fresh number is reserved for you.\n"
            "3️⃣ Open WhatsApp and register with the number shown.\n"
            "4️⃣ Tap <b>Get OTP</b> here — the SMS code arrives in this chat.\n"
            "5️⃣ If no SMS arrives, tap <b>Cancel &amp; Refund</b> and try again.\n\n"
            "<i>Tip: try a different country if one is out of stock.</i>"
        ),
    },
    "numchange": {
        "title": "TG Number Change",
        "short": "Number Change",
        "icon": "🔁",
        "service": TEMPORASMS_SERVICE_NUMCHANGE,
        "country": TEMPORASMS_COUNTRY_NUMCHANGE,
        "style": "primary",
        "tc_title": "TG Number Change — Terms & Conditions",
        "tc_body": (
            "This service gives you a fresh number to change the phone number "
            "on your existing Telegram account.\n\n"
            "A new virtual number is reserved from the panel for a limited "
            "time. Enter it in Telegram → Settings → Privacy &amp; Security → "
            "Phone Number → Change Number.\n\n"
            "If the code does not arrive, cancel the order to get an automatic "
            "refund to your balance."
        ),
        "guide": (
            "<b>How to change your TG number</b>\n\n"
            "1️⃣ Choose a country and tap it.\n"
            "2️⃣ Copy the number shown in the order card.\n"
            "3️⃣ In Telegram open <b>Settings → Privacy &amp; Security → "
            "Phone Number → Change Number</b>.\n"
            "4️⃣ Enter the number, then tap <b>Get OTP</b> here.\n"
            "5️⃣ Enter the code inside Telegram. Done ✅"
        ),
    },
    "allotp": {
        "title": "All Apps OTP",
        "short": "All Apps",
        "icon": "\U0001F9E9",
        "service": TEMPORASMS_SERVICE_ALLOTP,   # overridden by the selected app
        "country": TEMPORASMS_COUNTRY_ALLOTP,
        "style": "primary",
        "dynamic_apps": True,
        "tc_title": "All Apps OTP \u2014 Terms & Conditions",
        "tc_body": (
            "This panel gives you a fresh virtual number for <b>any app</b> \u2014 "
            "Telegram, WhatsApp, Instagram, Google, ChatGPT, Discord, TikTok and "
            "8,500+ more.\n\n"
            "Pick the app first, then pick the country. A live number is reserved "
            "from the panel for a limited time and the OTP is delivered straight "
            "into this chat.\n\n"
            "If no SMS arrives, cancel the order and the amount is refunded to "
            "your balance automatically.\n\n"
            "Read the guide below, then tap <b>Agree & Continue</b>."
        ),
        "guide": (
            "<b>How to use the All Apps OTP panel</b>\n\n"
            "1\ufe0f\u20e3 Tap <b>Browse All Apps</b> or <b>Search App</b> and pick the app.\n"
            "2\ufe0f\u20e3 Pick the country (or use <b>Search Country</b>).\n"
            "3\ufe0f\u20e3 Tap the country button \u2014 a number is reserved for you.\n"
            "4\ufe0f\u20e3 Enter that number in the app's signup screen.\n"
            "5\ufe0f\u20e3 Tap <b>Get OTP</b> here \u2014 the code arrives in this chat.\n"
            "6\ufe0f\u20e3 No SMS? Tap <b>Cancel & Refund</b> and try another country."
        ),
    },
}

# --------------------------------------------------------------------------
# All Apps catalogue (used by the All Apps OTP panel)
# slug = TemporaSMS service code, label = what the user sees
# --------------------------------------------------------------------------
ALL_APPS = [
    ("telegram", "\u2708\ufe0f Telegram"),
    ("whatsapp", "\U0001F4AC WhatsApp"),
    ("instagram", "\U0001F4F8 Instagram"),
    ("facebook", "\U0001F4D8 Facebook"),
    ("twitter", "\U0001F426 Twitter / X"),
    ("tiktok", "\U0001F3B5 TikTok"),
    ("google", "\U0001F50D Google / Gmail"),
    ("openai", "\U0001F916 ChatGPT / OpenAI"),
    ("discord", "\U0001F3AE Discord"),
    ("snapchat", "\U0001F47B Snapchat"),
    ("linkedin", "\U0001F4BC LinkedIn"),
    ("youtube", "\u25b6\ufe0f YouTube"),
    ("amazon", "\U0001F6D2 Amazon"),
    ("netflix", "\U0001F3AC Netflix"),
    ("paypal", "\U0001F4B3 PayPal"),
    ("uber", "\U0001F697 Uber"),
    ("bolt", "\U0001F695 Bolt"),
    ("tinder", "\U0001F525 Tinder"),
    ("bumble", "\U0001F41D Bumble"),
    ("binance", "\U0001FA99 Binance"),
    ("coinbase", "\U0001F4B0 Coinbase"),
    ("revolut", "\U0001F4B8 Revolut"),
    ("wise", "\U0001F4B1 Wise"),
    ("steam", "\U0001F579\ufe0f Steam"),
    ("twitch", "\U0001F4FA Twitch"),
    ("spotify", "\U0001F3A7 Spotify"),
    ("reddit", "\U0001F4E2 Reddit"),
    ("pinterest", "\U0001F4CC Pinterest"),
    ("signal", "\U0001F510 Signal"),
    ("viber", "\U0001F49C Viber"),
    ("line", "\U0001F7E2 LINE"),
    ("wechat", "\U0001F7E9 WeChat"),
    ("okcupid", "\U0001F49D OkCupid"),
    ("grindr", "\U0001F308 Grindr"),
    ("badoo", "\U0001F48B Badoo"),
    ("truecaller", "\U0001F4F2 Truecaller"),
    ("yahoo", "\U0001F4E7 Yahoo"),
    ("microsoft", "\U0001F4BB Microsoft"),
    ("apple", "\U0001F34E Apple ID"),
    ("adobe", "\U0001F3A8 Adobe"),
    ("canva", "\U0001F58C\ufe0f Canva"),
    ("notion", "\U0001F4DD Notion"),
    ("zoom", "\U0001F4F9 Zoom"),
    ("skype", "\u260E\ufe0f Skype"),
    ("deliveroo", "\U0001F6F5 Deliveroo"),
    ("doordash", "\U0001F355 DoorDash"),
    ("airbnb", "\U0001F3E0 Airbnb"),
    ("booking", "\U0001F3E8 Booking.com"),
    ("alipay", "\U0001F4B5 Alipay"),
    ("kakao", "\U0001F7E1 KakaoTalk"),
    ("zalo", "\U0001F537 Zalo"),
]
APP_LABELS = dict(ALL_APPS)


def _app_label(slug):
    return APP_LABELS.get(slug, slug)


def _app_icon(slug):
    label = _app_label(slug)
    return label.split(" ", 1)[0] if label else "\U0001F4F1"


def _clean_name(name):
    """Strip a leading flag/emoji (and provider noise) from a name."""
    from utils.flags import clean_name as _cn
    return _cn(name)


def _filter_apps(query):
    if not query:
        return list(ALL_APPS)
    q = query.strip().lower().lstrip("@")
    return [a for a in ALL_APPS if q in a[0].lower() or q in a[1].lower()]


# uid -> {"panel": key, "country": code, "order_id": str, "phone": str,
#         "price": float, "mode": "search"}
panel_state = {}
_cache = {}  # key -> {"ts": float, "countries": [...]}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _flag(code: str) -> str:
    """Resolve any country identifier (ISO code, slug, name, dial code) to a flag."""
    from utils.flags import flag_for
    return flag_for(code)


def _user_currency(uid):
    try:
        return get_user_currency(uid)
    except Exception:
        return "INR"


def _price_label(real_price, uid, cfg=None):
    """Real panel cost -> what the customer sees, in INR **and** USDT.

    The panel's real (cost) price is never leaked: the value shown is always
    ``real_price + owner_margin`` where the margin is either a percentage or a
    fixed amount in INR/USD (see /setmarkup and /setprofit).
    """
    if real_price is None:
        return "—"
    return format_dual_price(real_price, cfg)


def _display_inr(real_price, cfg=None):
    return apply_markup(real_price, cfg)


def _balance(uid):
    row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _terms_accepted(uid, key):
    row = cur.execute("SELECT value FROM settings WHERE key=?",
                      (f"pp_tc_{uid}_{key}",)).fetchone()
    return bool(row and row[0] == "1")


def _accept_terms(uid, key):
    cur.execute(
        "INSERT INTO settings (key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value='1'",
        (f"pp_tc_{uid}_{key}",),
    )
    db.commit()


def _selected_app(uid):
    """App slug currently selected in the All Apps OTP panel."""
    return (panel_state.get(uid) or {}).get("app")


def _service_for(key, uid=None):
    """TemporaSMS service code for a panel.

    The All Apps panel is dynamic: the service is whichever app the user picked.
    """
    if PANELS[key].get("dynamic_apps"):
        app = _selected_app(uid) if uid is not None else None
        return app or PANELS[key].get("service") or "telegram"
    return PANELS[key]["service"]


async def _countries_for(key, uid=None, force=False):
    """Cached live country list for a panel, with fallback.

    `force=True` bypasses the cache and re-queries the provider, which is what
    the Buy flow does when it finds a country without a live price.
    """
    service = _service_for(key, uid)
    cache_key = f"{key}:{service}"
    cached = _cache.get(cache_key)
    if not force and cached and time.time() - cached["ts"] < CACHE_TTL and cached["countries"]:
        return cached["countries"], True
    result = await temporasms.get_countries(service)
    if result.get("ok") and result.get("countries"):
        _cache[cache_key] = {"ts": time.time(), "countries": result["countries"]}
        return result["countries"], True
    if cached and cached["countries"]:
        return cached["countries"], False
    return temporasms.fallback_countries(), False


def _filter_countries(countries, query):
    if not query:
        return countries
    q = query.strip().lower()
    out = []
    for c in countries:
        if q in str(c.get("code", "")).lower() or q in str(c.get("name", "")).lower():
            out.append(c)
    return out


def _ensure_order_table():
    cur.execute("""
        CREATE TABLE IF NOT EXISTS panel_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            panel TEXT,
            country TEXT,
            phone TEXT,
            price REAL,
            real_price REAL,
            profit REAL,
            order_id TEXT,
            status TEXT DEFAULT 'pending',
            otp TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()


_ensure_order_table()


def _create_order(uid, key, country, phone, price, real_price, profit, order_id):
    cur.execute(
        "INSERT INTO panel_orders (user_id, panel, country, phone, price, real_price,"
        " profit, order_id, status) VALUES (?,?,?,?,?,?,?,?, 'pending')",
        (uid, key, country, phone, price, real_price, profit, order_id),
    )
    db.commit()
    return cur.lastrowid


def _update_order(order_id, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    cur.execute(f"UPDATE panel_orders SET {sets} WHERE order_id=?",
                (*fields.values(), order_id))
    db.commit()


async def _safe_edit(event, text, buttons=None):
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.edit(text, buttons=buttons)
        except MessageNotModifiedError:
            pass
    else:
        await event.respond(text, buttons=buttons)


# --------------------------------------------------------------------------
# screens
# --------------------------------------------------------------------------
async def show_panel_hub(event):
    btns = [
        [style_btn("💬 WhatsApp Account", b"pp_open|whatsapp", "success", icon=5408995930416362034)],
        [style_btn("🔁 TG Number Change", b"pp_open|numchange", "primary", icon=5409119256107297715)],
        [style_btn("🧩 All Apps OTP — 8,526+ Apps", b"pp_open|allotp", "success", icon=5409320020058584473)],
        [style_btn("🔍 Search All Services", b"all_apps_menu", "success", icon=5409098988156629257)],
        [style_btn("🆘 Help", b"pp_help", "primary", icon=6129732880529628243)],
        [style_btn("🔙 Back", b"dashboard_main", "danger", icon=6129812419028982717)],
    ]
    status = "✅ Live" if temporasms.configured() else "⚠️ TEMPORASMS_API_KEY missing"
    msg = (
        "<blockquote expandable>💚 <b>VTH PANEL SMS &amp; Virtual Number Activation</b>\n\n"
        "📱 <b>8,526+ apps &amp; platforms</b>\n"
        "🌍 Numbers from many countries\n"
        "📊 Live stock &amp; prices\n"
        "💸 Auto refund if no SMS arrives\n"
        "✈️ OTP delivered straight into chat\n\n"
        f"🔑 <b>Panel status:</b> {status}\n"
        "📈 <b>Rates:</b> cheapest country first</blockquote>"
    )
    await _safe_edit(event, msg, btns)


async def show_terms(event, key, country=None):
    p = PANELS[key]
    uid = event.sender_id
    panel_state.setdefault(uid, {})["panel"] = key
    header = ""
    if country:
        countries, _ = await _countries_for(key, uid)
        match = next((c for c in countries if c["code"] == country), None)
        if match:
            header = (f"\n\n{_flag(match['code'])} <b>{html.escape(_clean_name(match['name']))}</b>"
                      f" · {_price_label(match['price'], uid)}")
    msg = (
        f"<blockquote expandable>{p['icon']} <b>{p['tc_title']}</b>{header}\n\n"
        f"{p['tc_body']}</blockquote>"
    )
    btns = [
        [style_btn("📖 How to buy", f"pp_guide|{key}", "primary", icon=5409320020058584473)],
        [style_btn("✅ Agree & Continue", f"pp_agree|{key}", "success", icon=5408995930416362034)],
        [style_btn("❌ Cancel", b"pp_cancel", "danger", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)


async def show_guide(event, key):
    p = PANELS[key]
    msg = f"<blockquote expandable>📖 <b>{p['title']} — Guide</b>\n\n{p['guide']}</blockquote>"
    btns = [
        [style_btn("✅ Agree & Continue", f"pp_agree|{key}", "success", icon=5408995930416362034)],
        [style_btn("🔙 Back", f"pp_open|{key}", "danger", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)


async def show_allotp_hub(event, page=1, query=None):
    """All Apps OTP panel: browse / search every app, then pick a country."""
    uid = event.sender_id
    panel_state.setdefault(uid, {})["panel"] = "allotp"
    panel_state[uid].pop("app", None)
    panel_state[uid].pop("mode", None)

    apps = _filter_apps(query)
    total = len(apps)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    chunk = apps[start:start + PAGE_SIZE]

    if not chunk:
        msg = (
            "<blockquote expandable>\U0001F9E9 <b>All Apps OTP</b>\n\n"
            f"\U0001F615 No app matched <b>{html.escape(query or '')}</b>.\n"
            "Try another name, or tap <b>Browse All Apps</b>.</blockquote>"
        )
        btns = [
            [style_btn("\U0001F4DA Browse All Apps", b"pp_apps|1", "success", icon=5409320020058584473)],
            [style_btn("\U0001F50D Search App", b"pp_appsearch", "primary", icon=5409098988156629257)],
            [style_btn("\U0001F519 Back", b"pp_hub", "danger", icon=6129812419028982717)],
        ]
        return await _safe_edit(event, msg, btns)

    btns = []
    row = []
    for slug, label in chunk:
        row.append(style_btn(label[:60], f"pp_app|{slug}", "primary"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    nav = []
    if page > 1:
        nav.append(style_btn("\u2b05\ufe0f Prev", f"pp_apps|{page - 1}", "primary", icon=6129627894349045589))
    nav.append(style_btn(f"\U0001F4C4 {page}/{total_pages}", f"pp_apps|{page}", "primary"))
    if page < total_pages:
        nav.append(style_btn("Next \u27a1\ufe0f", f"pp_apps|{page + 1}", "primary", icon=6129732880529628243))
    btns.append(nav)

    btns.append([
        style_btn("\U0001F50D Search App", b"pp_appsearch", "primary", icon=5409098988156629257),
        style_btn("\U0001F30D Search Country", b"pp_csearch", "success", icon=5409098988156629257),
    ])
    btns.append([style_btn("\U0001F519 Back", b"pp_hub", "danger", icon=6129812419028982717)])

    status = "\u2705 Live" if temporasms.configured() else "\u26a0\ufe0f TEMPORASMS_API_KEY missing"
    search_line = f"\n\U0001F50E Filter: <b>{html.escape(query)}</b>" if query else ""
    msg = (
        "<blockquote expandable>\U0001F9E9 <b>All Apps OTP \u2014 8,526+ apps & platforms</b>\n\n"
        "\U0001F4F1 Pick any app, then pick a country \u2014 a fresh number is reserved "
        "and the OTP lands right here in this chat.\n\n"
        "\U0001F30D Numbers from many countries\n"
        "\U0001F4CA Live stock & prices\n"
        "\U0001F4B8 Auto refund if no SMS arrives\n"
        f"\U0001F511 <b>Panel status:</b> {status}{search_line}\n\n"
        f"<i>Page {page}/{total_pages} \u00b7 {total} apps</i></blockquote>"
    )
    await _safe_edit(event, msg, btns)


async def open_app(event, slug):
    """User picked an app -> show its country list."""
    uid = event.sender_id
    if slug not in APP_LABELS:
        return await event.answer("\u26a0\ufe0f Unknown app, please browse again.", alert=True)
    panel_state.setdefault(uid, {})["panel"] = "allotp"
    panel_state[uid]["app"] = slug
    panel_state[uid].pop("mode", None)
    await mongo_store.log_event(uid, "allotp_app_open", app=slug)
    await show_countries(event, "allotp", 1)


async def start_app_search(event):
    uid = event.sender_id
    panel_state.setdefault(uid, {})["panel"] = "allotp"
    panel_state[uid]["mode"] = "app_search"
    msg = (
        "<blockquote expandable>\U0001F50D <b>Search App \u2014 All Apps OTP</b>\n\n"
        "Send the app name (e.g. <code>telegram</code>, <code>instagram</code>, "
        "<code>chatgpt</code>, <code>discord</code>).</blockquote>"
    )
    btns = [
        [style_btn("\U0001F4DA Browse All Apps", b"pp_apps|1", "success", icon=5409320020058584473)],
        [style_btn("\U0001F519 Back", b"pp_open|allotp", "danger", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)


async def start_country_search(event, key="allotp"):
    """Country search. In the All Apps panel an app must be picked first."""
    uid = event.sender_id
    if PANELS[key].get("dynamic_apps") and not _selected_app(uid):
        panel_state.setdefault(uid, {})["mode"] = "country_search_pending"
        msg = (
            "<blockquote expandable>\U0001F30D <b>Search Country</b>\n\n"
            "First pick the app you want a number for \u2014 then you can search "
            "countries for it.</blockquote>"
        )
        btns = [[style_btn("\U0001F4DA Browse All Apps", b"pp_apps|1", "success", icon=5409320020058584473)]]
        return await _safe_edit(event, msg, btns)
    panel_state.setdefault(uid, {})["mode"] = "search"
    panel_state[uid]["panel"] = key
    app_line = ""
    if PANELS[key].get("dynamic_apps"):
        app_line = f" \u2014 {_app_icon(_selected_app(uid))} {html.escape(_clean_name(_app_label(_selected_app(uid))))}"
    msg = (
        f"<blockquote expandable>\U0001F50D <b>Search Country{app_line}</b>\n\n"
        "Send the country name or dial code (e.g. <code>India</code>, "
        "<code>+91</code>, <code>usa</code>).</blockquote>"
    )
    btns = [[style_btn("\U0001F519 Back", f"pp_open|{key}", "danger", icon=6129812419028982717)]]
    await _safe_edit(event, msg, btns)


async def show_countries(event, key, page=1, query=None):
    uid = event.sender_id
    p = PANELS[key]
    panel_state.setdefault(uid, {})["panel"] = key

    dynamic = p.get("dynamic_apps")
    app = _selected_app(uid) if dynamic else None
    if dynamic and not app:
        return await show_allotp_hub(event)

    countries, live = await _countries_for(key, uid)
    countries = _filter_countries(countries, query)
    cfg = get_markup_config()

    total = len(countries)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    chunk = countries[start:start + PAGE_SIZE]

    if not chunk:
        msg = (
            f"<blockquote expandable>{p['icon']} <b>{p['title']}</b>\n\n"
            f"😕 No country matched <b>{html.escape(query or '')}</b>.\n"
            "Try another name, or tap Refresh.</blockquote>"
        )
        btns = [
            [style_btn("🔍 Search Country", f"pp_search|{key}", "primary", icon=5409098988156629257)],
            [style_btn("🔄 Refresh", f"pp_open|{key}", "success", icon=5409320020058584473)],
            [style_btn("🔙 Back", b"pp_hub", "danger", icon=6129812419028982717)],
        ]
        return await _safe_edit(event, msg, btns)

    btns = []
    row = []
    for c in chunk:
        label = f"{_flag(c['code'])} {_clean_name(c['name'])} · {_price_label(c['price'], uid, cfg)}"
        row.append(style_btn(label[:60], f"pp_buy|{key}|{c['code']}", p["style"]))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    nav = []
    if page > 1:
        nav.append(style_btn("⬅️ Prev", f"pp_pg|{key}|{page - 1}", "primary", icon=6129627894349045589))
    nav.append(style_btn(f"📄 {page}/{total_pages}", f"pp_pg|{key}|{page}", "primary"))
    if page < total_pages:
        nav.append(style_btn("Next ➡️", f"pp_pg|{key}|{page + 1}", "primary", icon=6129732880529628243))
    btns.append(nav)

    btns.append([
        style_btn("🔍 Search Country", f"pp_search|{key}", "primary", icon=5409098988156629257),
        style_btn("🔄 Refresh", f"pp_open|{key}", "success", icon=5409320020058584473),
    ])
    if dynamic:
        btns.append([
            style_btn("🔄 Change App", b"pp_apps|1", "primary", icon=5409320020058584473),
            style_btn("🔙 Back", b"pp_apps|1", "danger", icon=6129812419028982717),
        ])
    else:
        btns.append([style_btn("🔙 Back", b"pp_hub", "danger", icon=6129812419028982717)])

    live_line = "🟢 Live rates" if live else "🟡 Cached rates (panel busy)"
    search_line = f"\n🔎 Filter: <b>{html.escape(query)}</b>" if query else ""
    if dynamic:
        service_line = (f"{p['icon']} <b>Service: All Apps OTP</b>\n"
                        f"{_app_icon(app)} <b>App:</b> {html.escape(_clean_name(_app_label(app)))}")
    else:
        service_line = f"{p['icon']} <b>Service: {p['title']}</b>"
    msg = (
        f"<blockquote expandable>{service_line}\n\n"
        f"Select a country to view available virtual numbers & live rates: "
        f"<b>{total} {'country' if total == 1 else 'countries'}</b> in stock.{search_line}\n\n"
        f"{live_line}\n<i>Page {page}/{total_pages}</i></blockquote>"
    )
    await _safe_edit(event, msg, btns)


async def start_search(event, key):
    uid = event.sender_id
    panel_state.setdefault(uid, {})["mode"] = "search"
    panel_state[uid]["panel"] = key
    msg = (
        f"<blockquote expandable>🔍 <b>Search Country — {PANELS[key]['title']}</b>\n\n"
        "Send the country name or dial code (e.g. <code>India</code>, "
        "<code>+91</code>, <code>usa</code>).</blockquote>"
    )
    btns = [[style_btn("🔙 Back", f"pp_open|{key}", "danger", icon=6129812419028982717)]]
    await _safe_edit(event, msg, btns)


async def handle_search_text(event, key, text, mode=None):
    """Text router for the panels: app search or country search."""
    uid = event.sender_id
    mode = mode or (panel_state.get(uid) or {}).get("mode")
    panel_state.get(uid, {}).pop("mode", None)
    if mode == "app_search":
        return await show_allotp_hub(event, 1, query=text)
    await show_countries(event, key, 1, query=text)


async def buy(event, key, code):
    uid = event.sender_id
    ensure_user(uid)
    countries, _ = await _countries_for(key, uid)
    match = next((c for c in countries if c["code"] == code), None)
    if not match:
        return await event.answer("⚠️ Country not available, refresh the panel.", alert=True)

    cfg = get_markup_config()
    real_price = match.get("price")
    if real_price is None:
        # The cached/fallback list had no live price.  Re-query the provider
        # once (bypassing the cache) before giving up.
        countries, _live = await _countries_for(key, uid, force=True)
        match = next((c for c in countries if c["code"] == code), match)
        real_price = match.get("price")
    if real_price is None:
        # Graceful, non-blocking fallback instead of a scary alert popup.
        name = _clean_name(match.get("name") or code)
        msg = (
            f"<blockquote expandable>{_flag(code)} <b>{html.escape(name)}</b>\n\n"
            "🟡 <b>Live pricing is temporarily unavailable</b> for this country.\n"
            "The number provider is busy right now. Please tap <b>Refresh</b> in a "
            "moment — no balance has been deducted.</blockquote>"
        )
        btns = [
            [style_btn("🔄 Refresh Price", f"pp_buy|{key}|{code}", "success", icon=5409320020058584473)],
            [style_btn("🔙 Back to Countries", f"pp_open|{key}", "primary", icon=6129812419028982717)],
        ]
        return await _safe_edit(event, msg, btns)

    display_inr = _display_inr(real_price, cfg)
    profit = display_inr - float(real_price)
    bal = _balance(uid)
    if bal < display_inr:
        return await event.answer(
            f"❌ Insufficient balance.\n"
            f"Need {format_dual_from_inr(display_inr)}\n"
            f"You have {format_dual_from_inr(bal)}",
            alert=True,
        )

    # reserve the number first, only charge on success
    result = await temporasms.buy_number(_service_for(key, uid), code)
    if not result.get("ok"):
        return await event.answer(
            f"⚠️ Could not reserve a number: {result.get('error') or 'panel busy'}",
            alert=True,
        )

    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (display_inr, uid))
    db.commit()

    order_id = result["order_id"]
    phone = result.get("phone") or "—"
    _create_order(uid, key, code, phone, display_inr, float(real_price), profit, order_id)
    await mongo_store.log_panel_order(
        uid, panel=key, country=code, phone=phone, price=display_inr,
        real_price=float(real_price), profit=profit, order_id=order_id, status="pending",
    )

    panel_state.setdefault(uid, {}).update(
        {"panel": key, "country": code, "order_id": order_id,
         "phone": phone, "price": display_inr}
    )

    msg = (
        f"<blockquote expandable>✅ <b>Number reserved — {PANELS[key]['title']}</b>\n\n"
        f"📞 <b>Number:</b> <code>{html.escape(phone)}</code>\n"
        f"{_flag(code)} <b>Country:</b> {html.escape(_clean_name(match['name']))}\n"
        f"💳 <b>Paid:</b> {format_dual_from_inr(display_inr)}\n"
        f"🆔 <b>Order:</b> <code>{html.escape(order_id)}</code>\n\n"
        "Use this number on the platform, then tap <b>Get OTP</b>.</blockquote>"
    )
    btns = [
        [style_btn("🔢 Get OTP", b"pp_getotp", "success", icon=5408995930416362034)],
        [style_btn("❌ Cancel & Refund", b"pp_refund", "danger", icon=6129812419028982717)],
        [style_btn("🔙 Back to countries", f"pp_open|{key}", "primary", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)
    asyncio.create_task(_auto_otp(uid, key, order_id, phone, display_inr))


async def _auto_otp(uid, key, order_id, phone, price):
    """Background poller: delivers the OTP automatically when it arrives."""
    try:
        result = await temporasms.wait_for_otp(order_id, attempts=18, delay=6)
        if not result.get("otp"):
            return
        _update_order(order_id, status="received", otp=result["otp"])
        await mongo_store.log_event(uid, "panel_otp", panel=key,
                                    order_id=order_id, otp=result["otp"])
        from utils.helpers import get_bot_instance
        bot = get_bot_instance()
        if bot is None:
            return
        await bot.send_message(
            uid,
            f"<blockquote expandable>🔢 <b>OTP received — {PANELS[key]['title']}</b>\n\n"
            f"📞 <b>Number:</b> <code>{html.escape(phone)}</code>\n"
            f"🔑 <b>Code:</b> <code>{html.escape(result['otp'])}</code>\n\n"
            "<i>Enter it on the platform now — it expires quickly.</i></blockquote>",
            buttons=[[style_btn("✅ Done", b"pp_hub", "success")]],
        )
    except Exception as exc:
        logger.warning(f"auto OTP task failed: {exc}")


async def get_otp_now(event):
    uid = event.sender_id
    st = panel_state.get(uid) or {}
    order_id = st.get("order_id")
    key = st.get("panel")
    if not order_id or key not in PANELS:
        return await event.answer("⚠️ No active order. Open a panel and buy a number first.",
                                  alert=True)
    await event.answer("⏳ Checking for SMS…")
    result = await temporasms.get_otp(order_id)
    if result.get("otp"):
        _update_order(order_id, status="received", otp=result["otp"])
        msg = (
            "<blockquote expandable>🔢 <b>OTP received</b>\n\n"
            f"📞 <b>Number:</b> <code>{html.escape(st.get('phone') or '—')}</code>\n"
            f"🔑 <b>Code:</b> <code>{html.escape(result['otp'])}</code></blockquote>"
        )
        btns = [[style_btn("✅ Done", b"pp_hub", "success")]]
    else:
        msg = (
            "<blockquote expandable>⏳ <b>Still waiting for the SMS…</b>\n\n"
            f"📞 <b>Number:</b> <code>{html.escape(st.get('phone') or '—')}</code>\n"
            f"Status: <b>{html.escape(str(result.get('status') or 'waiting'))}</b>\n\n"
            "<i>We also watch in the background and will send the code here "
            "automatically. If nothing arrives, cancel for a full refund.</i></blockquote>"
        )
        btns = [
            [style_btn("🔢 Check again", b"pp_getotp", "success", icon=5408995930416362034)],
            [style_btn("❌ Cancel & Refund", b"pp_refund", "danger", icon=6129812419028982717)],
        ]
    await _safe_edit(event, msg, btns)


async def refund(event):
    uid = event.sender_id
    st = panel_state.get(uid) or {}
    order_id = st.get("order_id")
    price = st.get("price") or 0
    key = st.get("panel")
    if not order_id:
        return await event.answer("⚠️ No active order to cancel.", alert=True)
    await temporasms.cancel(order_id)
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (price, uid))
    db.commit()
    _update_order(order_id, status="refunded")
    await mongo_store.log_event(uid, "panel_refund", panel=key,
                                order_id=order_id, amount=price)
    panel_state.get(uid, {}).pop("order_id", None)
    msg = (
        "<blockquote expandable>💸 <b>Order cancelled &amp; refunded</b>\n\n"
        f"🆔 <b>Order:</b> <code>{html.escape(order_id)}</code>\n"
        f"💰 <b>Refunded:</b> {format_dual_from_inr(price)}\n\n"
        "<i>The amount is back in your balance instantly.</i></blockquote>"
    )
    btns = [
        [style_btn("🔄 Try again", f"pp_open|{key}", "success", icon=5409320020058584473)],
        [style_btn("🔙 Panels", b"pp_hub", "danger", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)


async def show_help(event):
    msg = (
        "<blockquote expandable>🆘 <b>Panel Help</b>\n\n"
        "• <b>No SMS?</b> Wait up to 2 minutes, then tap Cancel &amp; Refund.\n"
        "• <b>Wrong country?</b> Go back and pick another one.\n"
        "• <b>Balance low?</b> Top up from the Recharge menu.\n"
        "• <b>Number rejected?</b> Some platforms block virtual numbers — "
        "try a different country.\n\n"
        "💬 Still stuck? Contact support from the main menu.</blockquote>"
    )
    btns = [[style_btn("🔙 Back", b"pp_hub", "danger", icon=6129812419028982717)]]
    await _safe_edit(event, msg, btns)


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------
def register_product_panels(bot):
    @bot.on(events.CallbackQuery(pattern=r"^pp_hub$"))
    async def cb_hub(e):
        await show_panel_hub(e)

    @bot.on(events.CallbackQuery(pattern=r"^pp_open\|(\w+)$"))
    async def cb_open(e):
        key = e.pattern_match.group(1).decode()
        if key not in PANELS:
            return await e.answer("Unknown panel", alert=True)
        uid = e.sender_id
        panel_state.setdefault(uid, {})["panel"] = key
        if not _terms_accepted(uid, key):
            return await show_terms(e, key)
        if PANELS[key].get("dynamic_apps"):
            return await show_allotp_hub(e)
        await show_countries(e, key, 1)

    @bot.on(events.CallbackQuery(pattern=r"^pp_guide\|(\w+)$"))
    async def cb_guide(e):
        await show_guide(e, e.pattern_match.group(1).decode())

    @bot.on(events.CallbackQuery(pattern=r"^pp_agree\|(\w+)$"))
    async def cb_agree(e):
        key = e.pattern_match.group(1).decode()
        if key not in PANELS:
            return await e.answer("Unknown panel", alert=True)
        _accept_terms(e.sender_id, key)
        await mongo_store.log_event(e.sender_id, "panel_terms_accepted", panel=key)
        if PANELS[key].get("dynamic_apps"):
            return await show_allotp_hub(e)
        await show_countries(e, key, 1)

    @bot.on(events.CallbackQuery(pattern=r"^pp_pg\|(\w+)\|(\d+)$"))
    async def cb_pg(e):
        key = e.pattern_match.group(1).decode()
        page = int(e.pattern_match.group(2))
        await show_countries(e, key, page)

    @bot.on(events.CallbackQuery(pattern=r"^pp_search\|(\w+)$"))
    async def cb_search(e):
        await start_country_search(e, e.pattern_match.group(1).decode())

    # --- All Apps OTP callbacks -----------------------------------------
    @bot.on(events.CallbackQuery(pattern=r"^pp_app\|([\w-]+)$"))
    async def cb_app(e):
        await open_app(e, e.pattern_match.group(1).decode())

    @bot.on(events.CallbackQuery(pattern=r"^pp_apps\|(\d+)$"))
    async def cb_apps(e):
        await show_allotp_hub(e, int(e.pattern_match.group(1)))

    @bot.on(events.CallbackQuery(pattern=r"^pp_appsearch$"))
    async def cb_appsearch(e):
        await start_app_search(e)

    @bot.on(events.CallbackQuery(pattern=r"^pp_csearch$"))
    async def cb_csearch(e):
        await start_country_search(e, "allotp")

    @bot.on(events.CallbackQuery(pattern=r"^pp_buy\|(\w+)\|([\w-]+)$"))
    async def cb_buy(e):
        key = e.pattern_match.group(1).decode()
        code = e.pattern_match.group(2).decode()
        await buy(e, key, code)

    @bot.on(events.CallbackQuery(pattern=r"^pp_getotp$"))
    async def cb_getotp(e):
        await get_otp_now(e)

    @bot.on(events.CallbackQuery(pattern=r"^pp_refund$"))
    async def cb_refund(e):
        await refund(e)

    @bot.on(events.CallbackQuery(pattern=r"^pp_cancel$"))
    async def cb_cancel(e):
        panel_state.get(e.sender_id, {}).pop("mode", None)
        await show_panel_hub(e)

    @bot.on(events.CallbackQuery(pattern=r"^pp_help$"))
    async def cb_help(e):
        await show_help(e)

    # --- slash commands -------------------------------------------------
    @bot.on(events.NewMessage(pattern=r"(?i)^/(whatsapp|wa)(?:@\w+)?$"))
    async def cmd_whatsapp(e):
        panel_state.setdefault(e.sender_id, {})["panel"] = "whatsapp"
        if not _terms_accepted(e.sender_id, "whatsapp"):
            return await show_terms(e, "whatsapp")
        await show_countries(e, "whatsapp", 1)

    @bot.on(events.NewMessage(pattern=r"(?i)^/(numchange|numberchange)(?:@\w+)?$"))
    async def cmd_numchange(e):
        panel_state.setdefault(e.sender_id, {})["panel"] = "numchange"
        if not _terms_accepted(e.sender_id, "numchange"):
            return await show_terms(e, "numchange")
        await show_countries(e, "numchange", 1)

    @bot.on(events.NewMessage(pattern=r"(?i)^/(allotp|otp|apps)(?:@\w+)?$"))
    async def cmd_allotp(e):
        panel_state.setdefault(e.sender_id, {})["panel"] = "allotp"
        if not _terms_accepted(e.sender_id, "allotp"):
            return await show_terms(e, "allotp")
        await show_allotp_hub(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/(panels|products)(?:@\w+)?$"))
    async def cmd_panels(e):
        await show_panel_hub(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/rates(?:@\w+)?$"))
    async def cmd_rates(e):
        cfg = get_markup_config()
        msg = (
            "<blockquote expandable>📈 <b>Live Panel Rates</b>\n\n"
            "💬 WhatsApp · 🔁 Number Change · 🧩 All Apps OTP\n"
            "🌍 All countries, cheapest first\n"
            f"⚙️ {describe_markup(cfg)}\n"
            f"💱 <b>Rate:</b> ₹{price_breakdown(100, cfg)['rate']:g} = 1 USDT\n\n"
            "<i>Every price is shown in <b>₹INR</b> and <b>USDT</b>. "
            "Open a panel to see the live price for your country.</i></blockquote>"
        )
        btns = [[style_btn("🧩 Open Panels", b"pp_hub", "success", icon=5409320020058584473)]]
        await e.respond(msg, buttons=btns)

    # --- text router for country search ---------------------------------
    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out and bool(e.text)
                              and not e.text.startswith("/")))
    async def pp_text_router(e):
        uid = e.sender_id
        # Never treat a persistent-menu tap as a search query.
        if matches_menu(e.raw_text, "buy account", "deposit", "profile", "my orders",
                        "balance", "stock", "refer", "support", "start", "close",
                        "help", "admin panel"):
            return
        st = panel_state.get(uid) or {}
        mode = st.get("mode")
        if mode not in ("search", "app_search", "country_search_pending"):
            return
        key = st.get("panel")
        if key not in PANELS:
            return
        if mode == "country_search_pending":
            # user typed a country before picking an app -> treat as app search
            panel_state[uid]["mode"] = "app_search"
            await handle_search_text(e, key, e.text, mode="app_search")
            raise events.StopPropagation
        await handle_search_text(e, key, e.text, mode=mode)
        raise events.StopPropagation
