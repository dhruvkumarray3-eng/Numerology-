"""Dedicated product panels — each button runs its own panel.

    💬 WhatsApp Account panel      -> live panel (service = TEMPORASMS_SERVICE_WHATSAPP)
    🔁 TG Number Change panel      -> live panel (service = TEMPORASMS_SERVICE_NUMCHANGE)
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
import difflib
import html
import re
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
from utils.keyboards import style_btn, matches_menu, SEARCH_EMOJI_ID, pe
from utils import temporasms
from utils.markup import (
    apply_markup, get_markup_config, describe_markup,
    format_dual_price, format_dual_from_inr, price_breakdown,
    apply_service_markup, format_service_dual_price, get_service_config,
)
from utils import mongo_store
from utils import stickers as sticker_engine
from utils import stock_details as stock_card
from utils.states import get_user_lock
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
            "3\ufe0f\u20e3 Tap the country \u2014 live <b>stock, rate & quality "
            "details</b> appear first. Then tap <b>Buy Now</b>.\n"
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


_EMOJI_FALLBACK = "\U0001F4F1"


def _has_emoji(text):
    """True when `text` starts with an emoji / pictograph."""
    if not text:
        return False
    first = text.strip()[0]
    code = ord(first)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2190 <= code <= 0x21FF
        or 0x2B00 <= code <= 0x2BFF
        or code in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139)
    )


def _ensure_emoji(label, fallback=_EMOJI_FALLBACK):
    """Guarantee every button label starts with an emoji.

    Some app names coming from the catalogue (or from a provider) have no
    leading icon.  Rather than showing a plain text button we prepend a
    sensible default so the whole panel looks consistent.
    """
    label = (label or "").strip()
    if not label:
        return fallback
    return label if _has_emoji(label) else f"{fallback} {label}"


def _country_label(code, name, price, uid, cfg=None, limit=60, service=None):
    """Country button label: flag + name + price (price omitted when unknown).

    The old label always ended with ``· —`` when the provider had no live
    price, which looked broken.  Now the dash is dropped completely and only
    the flag + country name are shown.
    """
    label = f"{_flag(code)} {_clean_name(name)}"
    price_txt = _price_label(price, uid, cfg, service)
    if price_txt and price_txt not in ("\u2014", "-", ""):
        label = f"{label} \u00b7 {price_txt}"
    return label[:limit]


# Common alternative names / spellings users type.  This is what makes
# searches like "ninja app", "chat gpt", "wa", "tg", "insta" or "x" resolve
# to the right provider service instead of returning "no app matched".
APP_ALIASES = {
    "ninja": "ninja",
    "ninja app": "ninja",
    "ninjaapp": "ninja",
    "tg": "telegram",
    "tele": "telegram",
    "telegram app": "telegram",
    "wa": "whatsapp",
    "whats app": "whatsapp",
    "whatsapp business": "whatsapp",
    "insta": "instagram",
    "ig": "instagram",
    "instgram": "instagram",
    "fb": "facebook",
    "meta": "facebook",
    "x": "twitter",
    "twitter x": "twitter",
    "gmail": "google",
    "google mail": "google",
    "chatgpt": "openai",
    "chat gpt": "openai",
    "gpt": "openai",
    "open ai": "openai",
    "yt": "youtube",
    "ms": "microsoft",
    "microsoft account": "microsoft",
    "apple id": "apple",
    "appleid": "apple",
    "amazon app": "amazon",
    "linked in": "linkedin",
    "tik tok": "tiktok",
    "snap chat": "snapchat",
    "kakao talk": "kakao",
    "kakaotalk": "kakao",
    "booking com": "booking",
    "booking.com": "booking",
    "true caller": "truecaller",
    "ok cupid": "okcupid",
    "door dash": "doordash",
}


def _norm(text):
    return " ".join(str(text or "").lower().replace("_", " ").replace("-", " ").split())


def _custom_slug(query):
    """Turn a free-text app name into a provider-safe service slug."""
    q = _norm(query)
    q = re.sub(r"\b(app|application|account|accounts)\b", " ", q)
    return re.sub(r"[^a-z0-9]", "", q)


def _filter_apps(query):
    """Fuzzy app search: exact -> alias -> prefix -> token -> similarity.

    Returns a list of ``(slug, label)`` tuples.  Unknown queries are NOT
    dropped: the caller can offer a "use this app" button so any provider
    service code (e.g. ``ninja``) still works.
    """
    if not query or not str(query).strip():
        return list(ALL_APPS)
    q = _norm(query).lstrip("@")
    q_compact = q.replace(" ", "")

    # 1) Direct alias hit.
    if q in APP_ALIASES:
        slug = APP_ALIASES[q]
        return [(s, l) for s, l in ALL_APPS if s == slug] or [(slug, slug.title())]

    scored = []
    for slug, label in ALL_APPS:
        s = _norm(slug)
        l = _norm(re.sub(r"[^\w\s]", " ", label))
        score = 0.0
        if q == s or q == l or q_compact == s.replace(" ", ""):
            score = 100
        elif l.startswith(q) or s.startswith(q):
            score = 80
        elif q in l or q in s:
            score = 60
        else:
            q_tokens = set(q.split())
            l_tokens = set(l.split()) | set(s.split())
            overlap = len(q_tokens & l_tokens)
            if overlap:
                score = 40 + overlap * 5
            else:
                ratio = max(
                    difflib.SequenceMatcher(None, q, l).ratio(),
                    difflib.SequenceMatcher(None, q_compact, s).ratio(),
                )
                if ratio >= 0.62:
                    score = ratio * 35
        if score > 0:
            scored.append((score, slug, label))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(slug, label) for _score, slug, label in scored]


# uid -> {"panel": key, "country": code, "order_id": str, "phone": str,
#         "price": float, "mode": "search"}
panel_state = {}
_AUTO_OTP_TASKS = {}  # order_id -> asyncio.Task
_cache = {}  # key -> {"ts": float, "countries": [...]}
_last_error = {}  # cache key -> human readable provider error


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


def _price_label(real_price, uid, cfg=None, service=None):
    """Real panel cost -> what the customer sees, in INR **and** USDT.

    The panel's real (cost) price is never leaked: the value shown is always
    ``real_price + owner_margin`` where the margin is either a percentage or a
    fixed amount in INR/USD (see /setmarkup and /setprofit).  When a panel
    ``service`` is supplied its own profit override (if enabled) is used.
    """
    if real_price is None:
        return "—"
    if service:
        return format_service_dual_price(real_price, service, uid=uid)
    return format_dual_price(real_price, cfg, uid=uid)


def _display_inr(real_price, cfg=None, service=None):
    if service:
        return apply_service_markup(real_price, service)
    return apply_markup(real_price, cfg)


def _balance(uid):
    row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _terms_accepted(uid, key):
    row = cur.execute("SELECT value FROM settings WHERE key=?",
                      (f"pp_tc_{uid}_{key}",)).fetchone()
    return bool(row and row[0] == "1")


def _accept_terms(uid, key):
    """Persist a terms acceptance and return ``True`` on success.

    A locked/corrupt DB must never kill the callback (which made the "Agree &
    Continue" button look dead).  We log, roll back and report failure so the
    caller can still move the user forward.
    """
    try:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'",
            (f"pp_tc_{uid}_{key}",),
        )
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - never break the panel
        logger.warning(f"Could not store terms acceptance for {uid}/{key}: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        return False


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

    The last provider error is stored in ``_last_error`` so the UI can explain
    *why* a panel is empty instead of silently showing a hardcoded flag list.
    """
    service = _service_for(key, uid)
    cache_key = f"{key}:{service}"
    cached = _cache.get(cache_key)
    if not force and cached and time.time() - cached["ts"] < CACHE_TTL and cached["countries"]:
        _last_error.pop(cache_key, None)
        return cached["countries"], True
    try:
        result = await asyncio.wait_for(temporasms.get_countries(service), timeout=20)
    except asyncio.TimeoutError:
        logger.warning(f"Panel get_countries({service}) timed out")
        result = {"ok": False, "countries": [],
                  "error": "The panel did not answer in time."}
    except Exception as exc:
        logger.warning(f"Panel get_countries({service}) failed: {exc}")
        result = {"ok": False, "countries": [], "error": str(exc)}
    if result.get("ok") and result.get("countries"):
        _cache[cache_key] = {"ts": time.time(), "countries": result["countries"]}
        _last_error.pop(cache_key, None)
        return result["countries"], True
    _last_error[cache_key] = result.get("error") or "No live data from the panel."
    if cached and cached["countries"]:
        return cached["countries"], False
    return temporasms.fallback_countries(), False


def _filter_countries(countries, query):
    """Fuzzy country filter shared by every OTP panel.

    Accepts a country name ("Japan"), ISO-2 ("jp"), ISO-3 ("JPN"), dial code
    ("+81" / "81") or an alias ("uk", "usa", "dubai").  Falls back to a plain
    substring test so provider-specific slugs still match.
    """
    if not query:
        return countries
    try:
        from utils.country_search import search_country_dicts
        matched = search_country_dicts(countries, query)
        if matched:
            return matched
    except Exception as _cs_ex:
        logger.debug(f"country_search failed, falling back: {_cs_ex}")

    q = str(query).strip().lower()
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
            return
        except MessageNotModifiedError:
            return
        except Exception as exc:  # noqa: BLE001 - never leave a dead button
            logger.warning(
                f"panel edit failed ({type(exc).__name__}: {exc}); "
                f"falling back to respond"
            )
    try:
        await event.respond(text, buttons=buttons)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"panel respond failed: {exc}")


# --------------------------------------------------------------------------
# screens
# --------------------------------------------------------------------------
async def show_panel_hub(event):
    btns = [
        [style_btn("💬 WhatsApp Account", b"pp_open|whatsapp", "success", icon="whatsapp")],
        [style_btn("🔁 TG Number Change", b"pp_open|numchange", "primary", icon="numchange")],
        [style_btn(f"🧩 All Apps OTP — {len(ALL_APPS)} Apps", b"pp_open|allotp", "success", icon="allapps_otp")],
        [style_btn("🔍 Search All Services", b"all_apps_menu", "success", icon=SEARCH_EMOJI_ID)],
        [style_btn("🆘 Help", b"pp_help", "primary", icon="help")],
        [style_btn("🔙 Back", b"dashboard_main", "danger", icon="back")],
    ]
    status = (pe("check", chr(0x2705)) + " Live") if temporasms.configured() else (pe("warning", chr(0x26A0) + chr(0xFE0F)) + " OTP key missing (Admin → 🔐 OTP / SMS Key)")
    brand = pe("crown", "💚")
    i_apps = pe("apps", "📱")
    i_globe = pe("globe", "🌍")
    i_chart = pe("chart", "📊")
    i_money = pe("money", "💸")
    i_tg = pe("telegram", "✈️")
    i_lock = pe("lock", "🔑")
    i_stats = pe("stats", "📈")
    msg = (
        f"<blockquote expandable>{brand} <b>VENDOR SELLINGS RDX</b> — "
        f"<b>SMS &amp; Virtual Number Activation</b>\n\n"
        f"{i_apps} <b>{len(ALL_APPS)} curated apps &amp; platforms</b> — any other app on request\n"
        f"{i_globe} Numbers from many countries\n"
        f"{i_chart} Live stock &amp; prices\n"
        f"{i_money} Auto refund if no SMS arrives\n"
        f"{i_tg} OTP delivered straight into chat\n\n"
        f"{i_lock} <b>Panel status:</b> {status}\n"
        f"{i_stats} <b>Rates:</b> cheapest country first</blockquote>"
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
            price_txt = _price_label(match["price"], uid, service=key)
            header = (f"\n\n{_flag(match['code'])} <b>{html.escape(_clean_name(match['name']))}</b>")
            if price_txt and price_txt not in ("—", "-", ""):
                header += f" · {price_txt}"
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
    msg = f"<blockquote expandable>{pe('doc', chr(0x1F4D6))} <b>{p['title']} — Guide</b>\n\n{p['guide']}</blockquote>"
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
            [style_btn("\U0001F50D Search App", b"pp_appsearch", "primary", icon=SEARCH_EMOJI_ID)],
            [style_btn("\U0001F519 Back", b"pp_hub", "danger", icon=6129812419028982717)],
        ]
        custom = _custom_slug(query)
        if custom:
            btns.insert(0, [style_btn(f"\U0001F195 Use \u201c{html.escape(query.strip())}\u201d",
                                      f"pp_app|{custom}", "success",
                                      icon=5373130604147654226)])
        return await _safe_edit(event, msg, btns)

    btns = []
    row = []
    for slug, label in chunk:
        row.append(style_btn(_ensure_emoji(label)[:60], f"pp_app|{slug}", "primary", icon="apps"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    nav = []
    if page > 1:
        nav.append(style_btn("\u2b05\ufe0f Prev", f"pp_apps|{page - 1}", "primary", icon=6129627894349045589))
    nav.append(style_btn(f"\U0001F4C4 {page}/{total_pages}", f"pp_apps|{page}", "primary", icon="doc"))
    if page < total_pages:
        nav.append(style_btn("Next \u27a1\ufe0f", f"pp_apps|{page + 1}", "primary", icon=6129732880529628243))
    btns.append(nav)

    btns.append([
        style_btn("\U0001F50D Search App", b"pp_appsearch", "primary", icon=SEARCH_EMOJI_ID),
        style_btn("\U0001F30D Search Country", b"pp_csearch", "success", icon=SEARCH_EMOJI_ID),
    ])
    btns.append([style_btn("\U0001F519 Back", b"pp_hub", "danger", icon=6129812419028982717)])

    status = (pe("check", chr(0x2705)) + " Live") if temporasms.configured() else (pe("warning", chr(0x26A0) + chr(0xFE0F)) + " OTP key missing (Admin → 🔐 OTP / SMS Key)")
    search_line = f"\n{pe('find', chr(0x1F50E))} Filter: <b>{html.escape(query)}</b>" if query else ""
    i_apps = pe("apps", chr(0x1F4F1))
    i_globe = pe("globe", chr(0x1F30D))
    i_chart = pe("chart", chr(0x1F4CA))
    i_money = pe("money", chr(0x1F4B8))
    i_lock = pe("lock", chr(0x1F511))
    msg = (
        f"<blockquote expandable>{pe('allapps', chr(0x1F9E9))} <b>All Apps OTP \u2014 {len(ALL_APPS)} apps &amp; platforms</b>\n\n"
        f"{i_apps} Pick any app, then pick a country \u2014 a fresh number is reserved "
        "and the OTP lands right here in this chat.\n\n"
        f"{i_globe} Numbers from many countries\n"
        f"{i_chart} Live stock &amp; prices\n"
        f"{i_money} Auto refund if no SMS arrives\n"
        f"{i_lock} <b>Panel status:</b> {status}{search_line}\n\n"
        f"<i>Page {page}/{total_pages} \u00b7 {total} apps</i></blockquote>"
    )
    await _safe_edit(event, msg, btns)


async def open_app(event, slug):
    """User picked an app -> show its country list.

    Unknown slugs are allowed on purpose: the All Apps panel is powered by the
    provider catalogue, so a service code the local list does not know about
    (e.g. ``ninja``) must still be queryable instead of dead-ending.
    """
    uid = event.sender_id
    slug = (slug or "").strip().lower()
    if not slug:
        return await event.answer("\u26a0\ufe0f Unknown app, please browse again.", alert=True)
    if slug not in APP_LABELS:
        # Register it for this session so labels / icons render sensibly.
        APP_LABELS[slug] = f"\U0001F50D {slug.title()}"
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
        f"<blockquote expandable>{pe('search', chr(0x1F50D))} <b>Search App \u2014 All Apps OTP</b>\n\n"
        "Send the app name (e.g. <code>telegram</code>, <code>instagram</code>, "
        "<code>chatgpt</code>, <code>discord</code>).</blockquote>"
    )
    btns = [
        [style_btn(chr(0x1F4DA) + " Browse All Apps", b"pp_apps|1", "success", icon="apps")],
        [style_btn(chr(0x1F519) + " Back", b"pp_open|allotp", "danger", icon="back")],
    ]
    await _safe_edit(event, msg, btns)


async def start_country_search(event, key="allotp"):
    """Country search. In the All Apps panel an app must be picked first."""
    uid = event.sender_id
    if PANELS[key].get("dynamic_apps") and not _selected_app(uid):
        # Never dead-end: default to Telegram so country search always works,
        # and let the user change the app afterwards.
        panel_state.setdefault(uid, {})["app"] = "telegram"
    panel_state.setdefault(uid, {})["mode"] = "search"
    panel_state[uid]["panel"] = key
    app_line = ""
    if PANELS[key].get("dynamic_apps"):
        app_line = f" \u2014 {_app_icon(_selected_app(uid))} {html.escape(_clean_name(_app_label(_selected_app(uid))))}"
    msg = (
        f"<blockquote expandable>{pe('search', chr(0x1F50D))} <b>Search Country{app_line}</b>\n\n"
        "Send a country name, ISO code or dial code \u2014 e.g. <code>Japan</code>, "
        "<code>JP</code>, <code>JPN</code>, <code>+81</code>, <code>India</code>, "
        "<code>+91</code>.</blockquote>"
    )
    btns = [[style_btn(chr(0x1F519) + " Back", f"pp_open|{key}", "danger", icon="back")]]
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
    if not live and not query:
        err = _last_error.get(f"{key}:{_service_for(key, uid)}")
        if err:
            msg = (
                f"<blockquote expandable>{p['icon']} <b>{p['title']}</b>\n\n"
                "\U0001F7E1 <b>No live numbers for this app right now.</b>\n\n"
                f"<i>{html.escape(str(err))}</i>\n\n"
                "Your OTP key is working \u2014 the provider just has no stock "
                "for this app at the moment. Tap Refresh in a moment, or open "
                "All Apps OTP to pick another app.</blockquote>"
            )
            btns = [
                [style_btn("\U0001F504 Refresh", f"pp_open|{key}", "success",
                           icon=5409320020058584473)],
                [style_btn("\U0001F9E9 All Apps OTP", b"pp_open|allotp",
                           "primary", icon="allapps_otp")],
                [style_btn("\U0001F519 Back", b"pp_hub", "danger",
                           icon=6129812419028982717)],
            ]
            return await _safe_edit(event, msg, btns)
    filtered = _filter_countries(countries, query)
    if query and not filtered:
        # The cached list may be stale or empty - force a live refresh once
        # before telling the user the country is not available.
        fresh, live = await _countries_for(key, uid, force=True)
        if fresh:
            countries = fresh
            filtered = _filter_countries(fresh, query)
    countries = filtered
    cfg = get_markup_config()

    total = len(countries)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    chunk = countries[start:start + PAGE_SIZE]

    if not chunk:
        resolved = None
        if query:
            try:
                from utils.country_search import resolve_country
                resolved = resolve_country(query)
            except Exception:
                resolved = None
        if resolved:
            dial_line = f" \u00b7 <code>+{resolved['dial']}</code>" if resolved.get('dial') else ""
            msg = (
                f"<blockquote expandable>{p['icon']} <b>{p['title']}</b>\n\n"
                f"{resolved['flag']} <b>{html.escape(resolved['name'])}</b> "
                f"(<code>{resolved['iso3'] or resolved['iso2'].upper()}</code>{dial_line})\n\n"
                "\U0001F7E1 <b>This country is not available on the panel right now.</b>\n"
                "The provider returned no numbers for it. Please pick another "
                "country or tap Refresh in a moment.</blockquote>"
            )
        else:
            msg = (
                f"<blockquote expandable>{p['icon']} <b>{p['title']}</b>\n\n"
                f"\U0001F615 No country matched <b>{html.escape(query or '')}</b>.\n"
                "Try a name (<code>Japan</code>), ISO code (<code>JP</code> / "
                "<code>JPN</code>) or dial code (<code>+81</code>).</blockquote>"
            )
        btns = [
            [style_btn("\U0001F50D Search Country", f"pp_search|{key}", "primary", icon=SEARCH_EMOJI_ID)],
            [style_btn("\U0001F504 Refresh", f"pp_open|{key}", "success", icon=5409320020058584473)],
            [style_btn("\U0001F519 Back", b"pp_hub", "danger", icon=6129812419028982717)],
        ]
        return await _safe_edit(event, msg, btns)

    btns = []
    row = []
    for c in chunk:
        label = _country_label(c["code"], c["name"], c["price"], uid, cfg, service=key)
        row.append(style_btn(label, f"pp_buy|{key}|{c['code']}", p["style"], icon="buy"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)

    nav = []
    if page > 1:
        nav.append(style_btn("⬅️ Prev", f"pp_pg|{key}|{page - 1}", "primary", icon=6129627894349045589))
    nav.append(style_btn(f"📄 {page}/{total_pages}", f"pp_pg|{key}|{page}", "primary", icon="doc"))
    if page < total_pages:
        nav.append(style_btn("Next ➡️", f"pp_pg|{key}|{page + 1}", "primary", icon=6129732880529628243))
    btns.append(nav)

    btns.append([
        style_btn("🔍 Search Country", f"pp_search|{key}", "primary", icon=SEARCH_EMOJI_ID),
        style_btn("🔄 Refresh", f"pp_open|{key}", "success", icon=5409320020058584473),
    ])
    if dynamic:
        btns.append([
            style_btn("🔄 Change App", b"pp_apps|1", "primary", icon=5409320020058584473),
            style_btn("🔙 Back", b"pp_apps|1", "danger", icon=6129812419028982717),
        ])
    else:
        btns.append([style_btn("🔙 Back", b"pp_hub", "danger", icon=6129812419028982717)])

    live_line = (pe("check", chr(0x1F7E2)) + " Live rates") if live else (pe("warning", chr(0x1F7E1)) + " Cached rates (panel busy)")
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

    # Premium custom-emoji logic: show the app logo (All Apps) or the
    # WhatsApp icon (WhatsApp panel) as a real premium emoji.  We force the
    # `apps` role so it also works when the global mode is "country".
    try:
        premium_name = _app_label(app) if (dynamic and app) else p["title"]
        await sticker_engine.send_for_event(event, premium_name, role="apps")
    except Exception as _sk_ex:
        logger.debug(f"premium app emoji skipped: {_sk_ex}")


async def start_search(event, key):
    uid = event.sender_id
    panel_state.setdefault(uid, {})["mode"] = "search"
    panel_state[uid]["panel"] = key
    msg = (
        f"<blockquote expandable>{pe('search', chr(0x1F50D))} <b>Search Country — {PANELS[key]['title']}</b>\n\n"
        "Send a country name, ISO code or dial code \u2014 e.g. <code>Japan</code>, "
        "<code>JP</code>, <code>JPN</code>, <code>+81</code>, <code>India</code>, "
        "<code>+91</code>.</blockquote>"
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


async def show_stock_details(event, key, code):
    """Country tapped -> LIVE stock details, never an instant purchase.

    Stock + rate are fetched live from the panel (cache is bypassed) and the
    card shows 2-3 quality lines plus the honest "not real Premium" note.
    """
    uid = event.sender_id
    p = PANELS[key]
    await event.answer("\u23f3 Fetching live stock\u2026")

    countries, live = await _countries_for(key, uid, force=True)
    match = next((c for c in countries if c["code"] == code), None)
    if not match:
        countries, live = await _countries_for(key, uid)
        match = next((c for c in countries if c["code"] == code), None)
    if not match:
        return await _safe_edit(
            event,
            f"<blockquote>{_flag(code)} <b>{html.escape(code.upper())}</b>\n\n"
            "\u26a0\ufe0f This country is not available on the panel right now. "
            "Please pick another one.</blockquote>",
            [[style_btn("\U0001F519 Back to Countries", f"pp_open|{key}", "danger",
                        icon=6129812419028982717)]],
        )

    cfg = get_markup_config()
    name = _clean_name(match.get("name") or code)
    real_price = match.get("price")
    stock = match.get("stock") or 0

    # ONE price only: panel cost + owner margin, service-aware, in INR + USDT.
    # The panel's real cost and the owner's profit are never shown separately.
    if real_price is None:
        rate_text = "\U0001F7E1 Live rate unavailable \u2014 tap Refresh"
    else:
        rate_text = _price_label(real_price, uid, cfg, service=key)

    extra_block = ""
    if p.get("dynamic_apps"):
        app = _selected_app(uid)
        if app:
            app_line = (f"{_app_icon(app)} <b>App:</b> "
                        f"{html.escape(_clean_name(_app_label(app)))}")
            extra_block = (extra_block + "\n" if extra_block else "") + app_line
    if not live:
        extra_block = (extra_block + "\n" if extra_block else "") + \
            "\U0001F7E1 <i>Cached rates (panel busy) \u2014 tap Refresh for live.</i>"

    # Never claim "out of stock" when the provider simply did not report a
    # count - that would block a purchase that actually works.
    if stock:
        stock_txt = stock_card.stock_text(stock)
    elif real_price is None:
        stock_txt = "\U0001F7E1 Live stock unavailable \u2014 tap Refresh"
    else:
        stock_txt = "\U0001F7E2 In stock (live count not reported)"

    msg = stock_card.details_message(
        title=f"{p['title']} \u2014 Stock Details",
        country_label=f"{_flag(code)} <b>{html.escape(name)}</b>",
        stock_text=stock_txt,
        rate_text=rate_text,
        kind=stock_card.KIND_OTP,
        extra_block=extra_block,
        balance_text=format_dual_from_inr(_balance(uid), uid=uid),
        rate_label="Your total price",
    )
    btns = [
        [style_btn("\u2705 Buy Now", f"pp_confirm|{key}|{code}", "success",
                   icon=5409320020058584473)],
        [style_btn("\U0001F504 Refresh Stock", f"pp_buy|{key}|{code}", "primary",
                   icon=5409320020058584473),
         style_btn("\U0001F519 Back", f"pp_open|{key}", "danger",
                   icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)

    # NOTE: the country flag is already rendered as a plain emoji inside the
    # details card.  We intentionally do NOT send a premium country-flag emoji
    # before purchase (owner request).


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

    display_inr = _display_inr(real_price, cfg, key)
    profit = display_inr - float(real_price)
    bal = _balance(uid)
    if bal < display_inr:
        return await event.answer(
            f"❌ Insufficient balance.\n"
            f"Need {format_dual_from_inr(display_inr, uid=uid)}\n"
            f"You have {format_dual_from_inr(bal, uid=uid)}",
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
        f"<blockquote expandable>{pe('check', chr(0x2705))} <b>Number reserved \u2014 {PANELS[key]['title']}</b>\n\n"
        f"{pe('phone', chr(0x1F4DE))} <b>Number:</b> <code>{html.escape(phone)}</code>\n"
        f"{_flag(code)} <b>Country:</b> {html.escape(_clean_name(match['name']))}\n"
        f"{pe('money', chr(0x1F4B3))} <b>Paid:</b> {format_dual_from_inr(display_inr, uid=uid)}\n"
        f"{pe('orders', chr(0x1F194))} <b>Order:</b> <code>{html.escape(order_id)}</code>\n\n"
        "Use this number on the platform, then tap <b>Get OTP</b>.</blockquote>"
    )
    btns = [
        [style_btn("🔢 Get OTP", b"pp_getotp", "success", icon=5408995930416362034)],
        [style_btn("❌ Cancel & Refund", b"pp_refund", "danger", icon=6129812419028982717)],
        [style_btn("🔙 Back to countries", f"pp_open|{key}", "primary", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)

    # Premium logic: country flag emoji + purchase celebration from the packs.
    try:
        await sticker_engine.send_for_event(event, code, role="flags")
        await sticker_engine.send_purchase_for_event(event)
    except Exception as _sk_ex:
        logger.debug(f"premium purchase emoji skipped: {_sk_ex}")

    _start_auto_otp(uid, key, order_id, phone, display_inr)


def _start_auto_otp(uid, key, order_id, phone, price):
    task = asyncio.create_task(_auto_otp(uid, key, order_id, phone, price))
    _AUTO_OTP_TASKS[order_id] = task
    return task


def _mark_order_received(order_id, otp):
    """Atomically accept an OTP only while the local order is still pending."""
    cur.execute(
        "UPDATE panel_orders SET status='received', otp=? "
        "WHERE order_id=? AND status='pending'",
        (str(otp), order_id),
    )
    changed = cur.rowcount == 1
    db.commit()
    return changed


async def _auto_otp(uid, key, order_id, phone, price):
    """Background poller: delivers the OTP automatically when it arrives."""
    try:
        result = await temporasms.wait_for_otp(order_id, attempts=18, delay=6)
        if not result.get("otp"):
            return
        if not _mark_order_received(order_id, result["otp"]):
            return
        await mongo_store.log_event(uid, "panel_otp", panel=key,
                                    order_id=order_id, otp=result["otp"])
        from utils.helpers import get_bot_instance
        bot = get_bot_instance()
        if bot is None:
            return
        sent = await bot.send_message(
            uid,
            f"<blockquote expandable>{pe('lock', chr(0x1F522))} <b>OTP received \u2014 {PANELS[key]['title']}</b>\n\n"
            f"{pe('phone', chr(0x1F4DE))} <b>Number:</b> <code>{html.escape(phone)}</code>\n"
            f"{pe('key', chr(0x1F511))} <b>Code:</b> <code>{html.escape(result['otp'])}</code>\n\n"
            "<i>\u2728 Tap the code to copy it \u2014 then enter it on the platform right away, it expires quickly.</i></blockquote>",
            buttons=[
                [style_btn("\U0001F4CB Copy Code", f"copy_otp|{result['otp']}", "success", icon=5409098988156629257)],
                [style_btn("\u2705 Done", b"pp_hub", "success", icon="check")],
            ],
        )
        try:
            await sticker_engine.send_purchase(bot, uid, reply_to=getattr(sent, "id", None))
        except Exception as _sk_ex:
            logger.debug(f"purchase emoji skipped: {_sk_ex}")
    except Exception as exc:
        logger.warning(f"auto OTP task failed: {exc}")
    finally:
        if _AUTO_OTP_TASKS.get(order_id) is asyncio.current_task():
            _AUTO_OTP_TASKS.pop(order_id, None)


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
        if not _mark_order_received(order_id, result["otp"]):
            return await event.answer("⚠️ This order is no longer active.", alert=True)
        msg = (
            f"<blockquote expandable>{pe('lock', chr(0x1F522))} <b>OTP received</b>\n\n"
            f"📞 <b>Number:</b> <code>{html.escape(st.get('phone') or '—')}</code>\n"
            f"🔑 <b>Code:</b> <code>{html.escape(result['otp'])}</code></blockquote>"
        )
        btns = [[style_btn("✅ Done", b"pp_hub", "success", icon="check")]]
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
    key = st.get("panel")
    if not order_id:
        return await event.answer("⚠️ No active order to cancel.", alert=True)

    async with get_user_lock(uid):
        order = cur.execute(
            "SELECT price, status, panel, phone FROM panel_orders "
            "WHERE order_id=? AND user_id=?",
            (order_id, uid),
        ).fetchone()
        if not order:
            return await event.answer("⚠️ Order not found for this account.", alert=True)
        price, status, key, phone = order
        if status != "pending":
            return await event.answer("⚠️ This order is already closed or has an OTP.", alert=True)
        cur.execute(
            "UPDATE panel_orders SET status='cancel_requested' "
            "WHERE order_id=? AND user_id=? AND status='pending'",
            (order_id, uid),
        )
        if cur.rowcount != 1:
            db.commit()
            return await event.answer("⚠️ This order is already being closed.", alert=True)
        db.commit()

    poll_task = _AUTO_OTP_TASKS.pop(order_id, None)
    resume_polling = poll_task is not None and not poll_task.done()
    if resume_polling:
        poll_task.cancel()
        await asyncio.gather(poll_task, return_exceptions=True)

    cancel_result = await temporasms.cancel(order_id)
    if not cancel_result.get("ok"):
        cur.execute(
            "UPDATE panel_orders SET status='pending' "
            "WHERE order_id=? AND user_id=? AND status='cancel_requested'",
            (order_id, uid),
        )
        db.commit()
        if resume_polling:
            _start_auto_otp(uid, key, order_id, phone or "—", price or 0)
        reason = html.escape(str(cancel_result.get("error") or "Provider cancellation was not confirmed")[:70])
        return await event.answer(
            f"⚠️ The provider did not confirm cancellation, so this order remains active and no refund was issued. {reason}",
            alert=True,
        )

    async with get_user_lock(uid):
        cur.execute(
            "UPDATE panel_orders SET status='refunded' "
            "WHERE order_id=? AND user_id=? AND status='cancel_requested'",
            (order_id, uid),
        )
        if cur.rowcount != 1:
            db.commit()
            return await event.answer("⚠️ The order changed state; no duplicate refund was issued.", alert=True)
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (price, uid))
        db.commit()

    await mongo_store.log_event(uid, "panel_refund", panel=key,
                                order_id=order_id, amount=price)
    panel_state.get(uid, {}).pop("order_id", None)
    msg = (
        f"<blockquote expandable>{pe('money', chr(0x1F4B8))} <b>Order cancelled &amp; refunded</b>\n\n"
        f"{pe('orders', chr(0x1F194))} <b>Order:</b> <code>{html.escape(order_id)}</code>\n"
        f"{pe('balance', chr(0x1F4B0))} <b>Refunded:</b> {format_dual_from_inr(price, uid=uid)}\n\n"
        "<i>The amount is back in your balance instantly.</i></blockquote>"
    )
    btns = [
        [style_btn("🔄 Try again", f"pp_open|{key}", "success", icon=5409320020058584473)],
        [style_btn("🔙 Panels", b"pp_hub", "danger", icon=6129812419028982717)],
    ]
    await _safe_edit(event, msg, btns)


async def show_help(event):
    msg = (
        f"<blockquote expandable>{pe('help', chr(0x1F198))} <b>Panel Help</b>\n\n"
        "\u2022 <b>No SMS?</b> Wait up to 2 minutes, then tap Cancel &amp; Refund.\n"
        "\u2022 <b>Wrong country?</b> Go back and pick another one.\n"
        "\u2022 <b>Balance low?</b> Top up from the Recharge menu.\n"
        "\u2022 <b>Number rejected?</b> Some platforms block virtual numbers \u2014 "
        "try a different country.\n\n"
        f"{pe('support', chr(0x1F4AC))} Still stuck? Contact support from the main menu.</blockquote>"
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

    @bot.on(events.CallbackQuery(pattern=r"^copy_otp\|(.+)$"))
    async def cb_copy_otp(e):
        """Deliver the OTP as a standalone <code> block -> one tap copies it."""
        otp = e.pattern_match.group(1).decode()
        try:
            await e.answer("\U0001F4CB Tap the code below to copy it!", alert=False)
        except Exception:
            pass
        try:
            await e.respond(
                f"<blockquote>\U0001F511 <b>\U0001D402\U0001D428\U0001D429\U0001D432 \U0001D402\U0001D428\U0001D41D\U0001D41E</b>\n\n"
                f"<code>{html.escape(otp)}</code>\n\n"
                f"<i>\u2728 One tap on the code copies it to your clipboard.</i></blockquote>"
            )
        except Exception as exc:
            logger.debug(f"copy_otp failed: {exc}")

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
        # Stop the button spinner immediately so a slow provider call later
        # cannot make the button look unresponsive.
        try:
            await e.answer()
        except Exception:
            pass
        _accept_terms(e.sender_id, key)
        try:
            await mongo_store.log_event(e.sender_id, "panel_terms_accepted", panel=key)
        except Exception:
            pass
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

    @bot.on(events.CallbackQuery(pattern=r"^pp_confirm\|(\w+)\|([\w-]+)$"))
    async def cb_pp_confirm(e):
        key = e.pattern_match.group(1).decode()
        code = e.pattern_match.group(2).decode()
        await buy(e, key, code)

    @bot.on(events.CallbackQuery(pattern=r"^pp_buy\|(\w+)\|([\w-]+)$"))
    async def cb_buy(e):
        key = e.pattern_match.group(1).decode()
        code = e.pattern_match.group(2).decode()
        await show_stock_details(e, key, code)

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
            f"<blockquote expandable>{pe('stats', chr(0x1F4C8))} <b>Live Panel Rates</b>\n\n"
            f"{pe('whatsapp', chr(0x1F4AC))} WhatsApp \u00b7 {pe('numchange', chr(0x1F501))} Number Change \u00b7 {pe('allapps', chr(0x1F9E9))} All Apps OTP\n"
            f"{pe('globe', chr(0x1F30D))} All countries, cheapest first\n"
            f"{pe('settings', chr(0x2699) + chr(0xFE0F))} {describe_markup(cfg)}\n"
            f"{pe('money', chr(0x1F4B1))} <b>Rate:</b> \u20b9{price_breakdown(100, cfg)['rate']:g} = 1 USDT\n\n"
            "<i>Every price is shown in <b>\u20b9INR</b> and <b>USDT</b>. "
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
        # Mutual exclusion: clear any pending All-Apps / buy search state so a
        # single message can never trigger two routers (duplicate replies).
        try:
            from plugins.all_apps import aa_search_state as _aa_state
            _aa_state.pop(uid, None)
        except Exception:
            pass
        try:
            from plugins.buy import search_state as _buy_search, user_states as _buy_states
            _buy_search[uid] = False
            if _buy_states.get(uid) == "AWAITING_COUNTRY":
                _buy_states[uid] = None
        except Exception:
            pass
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
