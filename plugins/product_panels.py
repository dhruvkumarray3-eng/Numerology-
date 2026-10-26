"""Dedicated product panels — each button runs its own panel.

    💬 WhatsApp Account panel      -> TemporaSMS (service = TEMPORASMS_SERVICE_WHATSAPP)
    🔁 TG Number Change panel      -> TemporaSMS (service = TEMPORASMS_SERVICE_NUMCHANGE)
    💻 Laptop / PC Account panel   -> TemporaSMS (service = TEMPORASMS_SERVICE_LAPTOP)

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
    TEMPORASMS_SERVICE_LAPTOP,
    TEMPORASMS_COUNTRY_WHATSAPP,
    TEMPORASMS_COUNTRY_NUMCHANGE,
    TEMPORASMS_COUNTRY_LAPTOP,
    format_price,
    logger,
)
from database import cur, db, ensure_user, get_user_currency
from utils.keyboards import style_btn
from utils import temporasms
from utils.markup import apply_markup, get_markup_config, describe_markup
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
    "laptop": {
        "title": "Laptop / PC Account",
        "short": "Laptop",
        "icon": "💻",
        "service": TEMPORASMS_SERVICE_LAPTOP,
        "country": TEMPORASMS_COUNTRY_LAPTOP,
        "style": "primary",
        "tc_title": "Laptop / PC Account — Terms & Conditions",
        "tc_body": (
            "A fresh virtual number is provided for creating a laptop / PC "
            "style account on the supported platform.\n\n"
            "Numbers are live from the panel and are released if the SMS is "
            "not received in time. Always tap <b>Get OTP</b> right after you "
            "request the code on the platform.\n\n"
            "Read the guide below, then click <b>Agree &amp; Continue</b>."
        ),
        "guide": (
            "<b>How to use the Laptop panel</b>\n\n"
            "1️⃣ Pick the country that matches the platform you are creating.\n"
            "2️⃣ Tap the country button to reserve a number.\n"
            "3️⃣ Enter that number on the platform's signup screen.\n"
            "4️⃣ Tap <b>Get OTP</b> here to receive the code.\n"
            "5️⃣ If nothing arrives, <b>Cancel &amp; Refund</b> and retry."
        ),
    },
}

# uid -> {"panel": key, "country": code, "order_id": str, "phone": str,
#         "price": float, "mode": "search"}
panel_state = {}
_cache = {}  # key -> {"ts": float, "countries": [...]}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _flag(code: str) -> str:
    code = (code or "").strip().lower()
    if len(code) == 2 and code.isalpha():
        return "".join(chr(0x1F1E6 + ord(ch) - ord("a")) for ch in code)
    named = {
        "england": "🇬🇧", "uk": "🇬🇧", "usa": "🇺🇸", "uae": "🇦🇪",
        "southafrica": "🇿🇦", "saudiarabia": "🇸🇦", "srilanka": "🇱🇰",
        "newzealand": "🇳🇿", "southkorea": "🇰🇷", "northkorea": "🇰🇵",
        "czech": "🇨🇿", "czechia": "🇨🇿",
    }
    return named.get(code, "🏳️")


def _user_currency(uid):
    try:
        return get_user_currency(uid)
    except Exception:
        return "INR"


def _price_label(real_price, uid, cfg=None):
    """Real cost -> what the customer sees. Never leaks the real value."""
    if real_price is None:
        return "—"
    display_inr = apply_markup(real_price, cfg)
    return format_price(display_inr, _user_currency(uid))


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


async def _countries_for(key):
    """Cached live country list for a panel, with fallback."""
    cached = _cache.get(key)
    if cached and time.time() - cached["ts"] < CACHE_TTL and cached["countries"]:
        return cached["countries"], True
    service = PANELS[key]["service"]
    result = await temporasms.get_countries(service)
    if result.get("ok") and result.get("countries"):
        _cache[key] = {"ts": time.time(), "countries": result["countries"]}
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
        [style_btn("💻 Laptop / PC Account", b"pp_open|laptop", "primary", icon=5409320020058584473)],
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
        countries, _ = await _countries_for(key)
        match = next((c for c in countries if c["code"] == country), None)
        if match:
            header = (f"\n\n{_flag(match['code'])} <b>{html.escape(match['name'])}</b>"
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


async def show_countries(event, key, page=1, query=None):
    uid = event.sender_id
    p = PANELS[key]
    panel_state.setdefault(uid, {})["panel"] = key
    countries, live = await _countries_for(key)
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
        label = f"{_flag(c['code'])} {c['name']} · {_price_label(c['price'], uid, cfg)}"
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
    btns.append([style_btn("🔙 Back", b"pp_hub", "danger", icon=6129812419028982717)])

    live_line = "🟢 Live rates" if live else "🟡 Cached rates (panel busy)"
    search_line = f"\n🔎 Filter: <b>{html.escape(query)}</b>" if query else ""
    msg = (
        f"<blockquote expandable>{p['icon']} <b>Service: {p['title']}</b>\n\n"
        f"Select a country to view available virtual numbers &amp; live rates: "
        f"<b>{total} countries</b> in stock.{search_line}\n\n"
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


async def handle_search_text(event, key, text):
    uid = event.sender_id
    panel_state.get(uid, {}).pop("mode", None)
    await show_countries(event, key, 1, query=text)


async def buy(event, key, code):
    uid = event.sender_id
    ensure_user(uid)
    countries, _ = await _countries_for(key)
    match = next((c for c in countries if c["code"] == code), None)
    if not match:
        return await event.answer("⚠️ Country not available, refresh the panel.", alert=True)

    cfg = get_markup_config()
    real_price = match.get("price")
    if real_price is None:
        return await event.answer(
            "⚠️ Live price for this country is unavailable right now. "
            "Please refresh or pick another country.", alert=True)

    display_inr = _display_inr(real_price, cfg)
    profit = display_inr - float(real_price)
    bal = _balance(uid)
    if bal < display_inr:
        return await event.answer(
            f"❌ Insufficient balance.\nNeed {format_price(display_inr, _user_currency(uid))}, "
            f"you have {format_price(bal, _user_currency(uid))}.",
            alert=True,
        )

    # reserve the number first, only charge on success
    result = await temporasms.buy_number(PANELS[key]["service"], code)
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
        f"{_flag(code)} <b>Country:</b> {html.escape(match['name'])}\n"
        f"💳 <b>Paid:</b> {format_price(display_inr, _user_currency(uid))}\n"
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
        f"💰 <b>Refunded:</b> {format_price(price, _user_currency(uid))}\n\n"
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
        await show_countries(e, key, 1)

    @bot.on(events.CallbackQuery(pattern=r"^pp_pg\|(\w+)\|(\d+)$"))
    async def cb_pg(e):
        key = e.pattern_match.group(1).decode()
        page = int(e.pattern_match.group(2))
        await show_countries(e, key, page)

    @bot.on(events.CallbackQuery(pattern=r"^pp_search\|(\w+)$"))
    async def cb_search(e):
        await start_search(e, e.pattern_match.group(1).decode())

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

    @bot.on(events.NewMessage(pattern=r"(?i)^/(laptop|pc)(?:@\w+)?$"))
    async def cmd_laptop(e):
        panel_state.setdefault(e.sender_id, {})["panel"] = "laptop"
        if not _terms_accepted(e.sender_id, "laptop"):
            return await show_terms(e, "laptop")
        await show_countries(e, "laptop", 1)

    @bot.on(events.NewMessage(pattern=r"(?i)^/(panels|products)(?:@\w+)?$"))
    async def cmd_panels(e):
        await show_panel_hub(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/rates(?:@\w+)?$"))
    async def cmd_rates(e):
        cfg = get_markup_config()
        msg = (
            "<blockquote expandable>📈 <b>Live Panel Rates</b>\n\n"
            "💬 WhatsApp · 🔁 Number Change · 💻 Laptop\n"
            "🌍 All countries, cheapest first\n"
            f"⚙️ {describe_markup(cfg)}\n\n"
            "<i>Open a panel to see the current price for your country.</i></blockquote>"
        )
        btns = [[style_btn("🧩 Open Panels", b"pp_hub", "success", icon=5409320020058584473)]]
        await e.respond(msg, buttons=btns)

    # --- text router for country search ---------------------------------
    @bot.on(events.NewMessage(func=lambda e: e.is_private and not e.out and bool(e.text)
                              and not e.text.startswith("/")))
    async def pp_text_router(e):
        uid = e.sender_id
        st = panel_state.get(uid) or {}
        if st.get("mode") != "search":
            return
        key = st.get("panel")
        if key not in PANELS:
            return
        await handle_search_text(e, key, e.text)
        raise events.StopPropagation
