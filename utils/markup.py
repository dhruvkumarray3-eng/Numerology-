"""Owner-controlled profit engine.

The user must NEVER see the panel's real (cost) price. Every price that is
shown or charged is:

    display_price = real_price + owner_profit

where `owner_profit` is either

  * a percentage of the real price   -> mode = "percent"
  * a fixed amount in INR            -> mode = "fixed", currency = INR
  * a fixed amount in USD            -> mode = "fixed", currency = USD
                                       (converted to INR at USDT_TO_INR)

Settings live in the `settings` table so the owner can change them live from
Telegram with /setmarkup or /setprofit. Nothing here ever raises: on any
problem we fall back to a sane default so the bot keeps working.
"""
import math

from config import (
    DEFAULT_MARKUP_MODE,
    DEFAULT_MARKUP_PERCENT,
    DEFAULT_MARKUP_FIXED,
    DEFAULT_MARKUP_CURRENCY,
    DEFAULT_CURRENCY,
    CURRENCY_SYMBOLS,
    convert_from_inr,
    USDT_TO_INR,
    logger,
)

# settings keys
K_MODE = "markup_mode"
K_PERCENT = "markup_percent"
K_FIXED = "markup_fixed"
K_CURRENCY = "markup_currency"

_VALID_MODES = ("percent", "fixed")
_VALID_CURRENCIES = ("INR", "USD")


def _db():
    from database import cur, db
    return cur, db


def _get(key, default=None):
    try:
        cur, _ = _db()
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row and row[0] not in (None, ""):
            return row[0]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"markup read failed for {key}: {exc}")
    return default


def _set(key, value):
    try:
        cur, db = _db()
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        db.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"markup write failed for {key}: {exc}")
        return False


def get_markup_config():
    """Return the current owner profit configuration."""
    mode = str(_get(K_MODE, DEFAULT_MARKUP_MODE)).strip().lower()
    if mode not in _VALID_MODES:
        mode = "percent"
    try:
        percent = float(_get(K_PERCENT, DEFAULT_MARKUP_PERCENT))
    except (TypeError, ValueError):
        percent = DEFAULT_MARKUP_PERCENT
    try:
        fixed = float(_get(K_FIXED, DEFAULT_MARKUP_FIXED))
    except (TypeError, ValueError):
        fixed = DEFAULT_MARKUP_FIXED
    currency = str(_get(K_CURRENCY, DEFAULT_MARKUP_CURRENCY)).strip().upper()
    if currency not in _VALID_CURRENCIES:
        currency = "INR"
    return {
        "mode": mode,
        "percent": max(0.0, percent),
        "fixed": max(0.0, fixed),
        "currency": currency,
    }


def set_markup(mode=None, percent=None, fixed=None, currency=None):
    """Persist a new profit configuration. Only provided fields are changed."""
    changed = {}
    if mode is not None:
        mode = str(mode).strip().lower()
        if mode in _VALID_MODES:
            _set(K_MODE, mode)
            changed["mode"] = mode
    if percent is not None:
        try:
            p = max(0.0, float(percent))
            _set(K_PERCENT, p)
            changed["percent"] = p
        except (TypeError, ValueError):
            pass
    if fixed is not None:
        try:
            f = max(0.0, float(fixed))
            _set(K_FIXED, f)
            changed["fixed"] = f
        except (TypeError, ValueError):
            pass
    if currency is not None:
        cur_code = str(currency).strip().upper()
        if cur_code in _VALID_CURRENCIES:
            _set(K_CURRENCY, cur_code)
            changed["currency"] = cur_code
    return changed


def profit_in_inr(real_price_inr, config=None):
    """How much the owner earns on a single sale, in INR."""
    cfg = config or get_markup_config()
    try:
        real = max(0.0, float(real_price_inr))
    except (TypeError, ValueError):
        real = 0.0
    if cfg["mode"] == "percent":
        return real * (cfg["percent"] / 100.0)
    if cfg["currency"] == "USD":
        return cfg["fixed"] * float(USDT_TO_INR)
    return cfg["fixed"]


def apply_markup(real_price_inr, config=None, minimum=1.0):
    """Real cost -> the price the customer sees/charges (INR, rounded up).

    Never returns a value below `minimum` so a panel can't accidentally be
    sold for zero.
    """
    try:
        real = max(0.0, float(real_price_inr))
    except (TypeError, ValueError):
        real = 0.0
    final = real + profit_in_inr(real, config)
    if final < minimum:
        final = minimum
    return float(math.ceil(final))


def describe_markup(config=None):
    """Human readable one-liner for admin screens."""
    cfg = config or get_markup_config()
    if cfg["mode"] == "percent":
        return f"{cfg['percent']:g}% profit on every sale"
    symbol = "₹" if cfg["currency"] == "INR" else "$"
    return f"{symbol}{cfg['fixed']:g} fixed profit per sale ({cfg['currency']})"


# ---------------------------------------------------------------------------
# Dual-currency display (USDT + INR)
# ---------------------------------------------------------------------------
# The customer always sees the owner's selling price in BOTH currencies:
#
#     ₹<INR>  ·  <USDT> USDT
#
# where the INR value is  real_panel_cost + owner_profit  and the USDT value
# is that same INR amount converted at the live USDT_TO_INR rate.  The real
# panel cost is NEVER exposed to the user.

def get_usdt_rate():
    """Current USDT -> INR rate (never raises, never returns 0)."""
    try:
        rate = float(USDT_TO_INR)
    except (TypeError, ValueError):
        rate = 88.0
    return rate if rate > 0 else 88.0


def usdt_from_inr(amount_inr, rate=None):
    """Convert an INR amount to USDT (4 dp, safe on bad input)."""
    try:
        inr = max(0.0, float(amount_inr))
    except (TypeError, ValueError):
        inr = 0.0
    r = float(rate) if rate else get_usdt_rate()
    if r <= 0:
        r = get_usdt_rate()
    return round(inr / r, 4)


def format_usdt(amount_usdt, decimals=2):
    """'1.42 USDT' style label."""
    try:
        val = max(0.0, float(amount_usdt))
    except (TypeError, ValueError):
        val = 0.0
    return f"{val:,.{decimals}f} USDT"


def format_inr(amount_inr):
    """'₹1,299' style label (INR is shown without decimals)."""
    try:
        val = float(amount_inr)
    except (TypeError, ValueError):
        val = 0.0
    return f"₹{val:,.0f}"


def price_breakdown(real_price_inr, config=None):
    """Full price maths for one item.

    Returns a dict:
        real_inr    -> panel's real cost (owner-only, never shown to users)
        profit_inr  -> owner profit on this sale
        inr         -> what the customer pays, in INR
        usdt        -> same amount expressed in USDT
        rate        -> USDT->INR rate used
    """
    cfg = config or get_markup_config()
    try:
        real = max(0.0, float(real_price_inr))
    except (TypeError, ValueError):
        real = 0.0
    final_inr = apply_markup(real, cfg)
    rate = get_usdt_rate()
    return {
        "real_inr": real,
        "profit_inr": round(final_inr - real, 2),
        "inr": final_inr,
        "usdt": usdt_from_inr(final_inr, rate),
        "rate": rate,
    }


def format_dual_price(real_price_inr, config=None, uid=None, currency=None):
    """The user-facing price label, honouring the user's currency setting.

    * ``INR``  -> ``₹1,299 · 14.76 USDT`` (both, as the owner asked)
    * ``USDT`` -> ``14.76 USDT`` (USDT only)
    * ``USD`` / ``EUR`` / ``GBP`` -> converted amount in that currency

    Returns an em-dash when the price is unknown/invalid so callers never show
    a misleading ``₹1`` for a country that simply has no live price.
    """
    if real_price_inr is None:
        return "—"
    try:
        float(real_price_inr)
    except (TypeError, ValueError):
        return "—"
    b = price_breakdown(real_price_inr, config)
    return format_user_amount(b["inr"], uid=uid, currency=currency)


def format_dual_from_inr(amount_inr, uid=None, currency=None):
    """User-facing label when the INR amount is already the final price."""
    try:
        inr = max(0.0, float(amount_inr))
    except (TypeError, ValueError):
        inr = 0.0
    return format_user_amount(inr, uid=uid, currency=currency)


def _resolve_currency(uid=None, currency=None):
    """Resolve the display currency for a user (never raises)."""
    if currency:
        return str(currency).strip().upper()
    if uid is not None:
        try:
            from database import get_user_currency
            return str(get_user_currency(uid) or DEFAULT_CURRENCY).strip().upper()
        except Exception:
            pass
    return str(DEFAULT_CURRENCY or "INR").strip().upper()


def format_user_amount(amount_inr, uid=None, currency=None):
    """Format an INR amount according to the user's currency preference.

    This is the single source of truth for every user-facing balance, price,
    deposit and spend label in the bot.
    """
    code = _resolve_currency(uid, currency)
    try:
        inr = float(amount_inr)
    except (TypeError, ValueError):
        inr = 0.0

    if code == "USDT":
        return format_usdt(usdt_from_inr(inr))
    if code in ("INR", "BOTH"):
        return f"{format_inr(inr)} · {format_usdt(usdt_from_inr(inr))}"
    symbol = CURRENCY_SYMBOLS.get(code)
    if not symbol:
        return f"{format_inr(inr)} · {format_usdt(usdt_from_inr(inr))}"
    value = convert_from_inr(inr, code)
    return f"{symbol}{value:,.2f}"


def format_user_amount_plain(amount_inr, uid=None, currency=None):
    """Same as :func:`format_user_amount` but without the USDT suffix.

    Used where space is tight (button labels) and the currency mode is a
    single-currency one.
    """
    code = _resolve_currency(uid, currency)
    try:
        inr = float(amount_inr)
    except (TypeError, ValueError):
        inr = 0.0
    if code == "USDT":
        return format_usdt(usdt_from_inr(inr))
    if code in ("INR", "BOTH"):
        return format_inr(inr)
    symbol = CURRENCY_SYMBOLS.get(code, "₹")
    return f"{symbol}{convert_from_inr(inr, code):,.2f}"


# ---------------------------------------------------------------------------
# Per-service profit overrides
# ---------------------------------------------------------------------------
# The owner can price each product line independently:
#
#     whatsapp   -> WhatsApp Account panel
#     numchange  -> TG Number Change panel
#     allotp     -> All Apps OTP panel
#     smm        -> SMM services (per 1000 units)
#     lzt        -> LZT market Telegram accounts
#
# Every service starts OUT of override mode and simply inherits the global
# configuration above, so nothing changes for existing deployments.  Once the
# owner enables an override for a service, only that service uses its own
# numbers - the others keep following the global setting.

SERVICES = {
    "whatsapp": "WhatsApp Account",
    "numchange": "TG Number Change",
    "allotp": "All Apps OTP",
    "smm": "SMM Services",
    "lzt": "LZT TG Accounts",
}

SERVICE_ORDER = ("whatsapp", "numchange", "allotp", "smm", "lzt")

# ---------------------------------------------------------------------------
# Per-server profit overrides
# ---------------------------------------------------------------------------
# A "server" is one of the catalogues the user picks from the Servers screen.
# The owner asked to be able to set a separate margin for *every* server, not
# just every service.  Server targets reuse the exact same storage scheme as
# services (``markup_svc_<key>_<field>``) so the admin console, the preview and
# the reset logic all work unchanged.
SERVER_TARGETS = {
    "srv_bulk": "Server-1 \u00b7 Bulk TG",
    "srv_nonspam": "Server-2 \u00b7 Good Quality TG",
    "srv_numchange": "Server-3 \u00b7 TG Number Change",
    "srv_spam": "Server-4 \u00b7 Cheap / Phishing",
    "srv_whatsapp": "WhatsApp Server",
    "srv_allotp": "All Apps OTP Server",
}

SERVER_ORDER = ("srv_bulk", "srv_nonspam", "srv_numchange", "srv_spam",
                "srv_whatsapp", "srv_allotp")

# SERVERS_CONFIG / buy.py "mode" -> server target key.
MODE_TO_SERVER = {
    "bulk": "srv_bulk",
    "nonspam": "srv_nonspam",
    "numchange": "srv_numchange",
    "spam": "srv_spam",
    "whatsapp": "srv_whatsapp",
    "allotp": "srv_allotp",
}

# Every price target the owner can tune (services + servers).
TARGETS = {**SERVICES, **SERVER_TARGETS}


def label_for(target):
    """Display name for a service *or* server pricing target."""
    return TARGETS.get(target) or SERVICES.get(target) or str(target)


def is_server_target(target):
    return target in SERVER_TARGETS


def server_target_for_mode(mode):
    """Map a server/buy mode ('bulk', 'spam', ...) to its pricing target."""
    return MODE_TO_SERVER.get(str(mode or "").strip().lower())


def _svc_key(service, field):
    return f"markup_svc_{service}_{field}"


def is_service_override(service):
    """True when this service/server has its own profit numbers switched on."""
    if service not in TARGETS:
        return False
    return str(_get(_svc_key(service, "enabled"), "0")).strip() in ("1", "true", "yes", "on")


def get_service_config(service):
    """Profit configuration that applies to one service *or* server.

    Returns the global config (plus ``service``/``override`` metadata) when the
    target has no override enabled, otherwise the target's own numbers.
    """
    if service not in TARGETS:
        cfg = dict(get_markup_config())
        cfg.update({"service": service, "override": False})
        return cfg

    if not is_service_override(service):
        cfg = dict(get_markup_config())
        cfg.update({"service": service, "override": False})
        return cfg

    base = get_markup_config()
    mode = str(_get(_svc_key(service, "mode"), base["mode"])).strip().lower()
    if mode not in _VALID_MODES:
        mode = base["mode"]
    try:
        percent = float(_get(_svc_key(service, "percent"), base["percent"]))
    except (TypeError, ValueError):
        percent = base["percent"]
    try:
        fixed = float(_get(_svc_key(service, "fixed"), base["fixed"]))
    except (TypeError, ValueError):
        fixed = base["fixed"]
    currency = str(_get(_svc_key(service, "currency"), base["currency"])).strip().upper()
    if currency not in _VALID_CURRENCIES:
        currency = base["currency"]
    return {
        "mode": mode,
        "percent": max(0.0, percent),
        "fixed": max(0.0, fixed),
        "currency": currency,
        "service": service,
        "override": True,
    }


def set_service_markup(service, mode=None, percent=None, fixed=None,
                       currency=None, enabled=True):
    """Persist a per-service / per-server profit override."""
    if service not in TARGETS:
        return {}
    changed = {}
    if enabled:
        _set(_svc_key(service, "enabled"), "1")
        changed["enabled"] = True
    if mode is not None:
        mode = str(mode).strip().lower()
        if mode in _VALID_MODES:
            _set(_svc_key(service, "mode"), mode)
            changed["mode"] = mode
    if percent is not None:
        try:
            p = max(0.0, float(percent))
            _set(_svc_key(service, "percent"), p)
            changed["percent"] = p
        except (TypeError, ValueError):
            pass
    if fixed is not None:
        try:
            f = max(0.0, float(fixed))
            _set(_svc_key(service, "fixed"), f)
            changed["fixed"] = f
        except (TypeError, ValueError):
            pass
    if currency is not None:
        code = str(currency).strip().upper()
        if code in _VALID_CURRENCIES:
            _set(_svc_key(service, "currency"), code)
            changed["currency"] = code
    return changed


def reset_service_markup(service):
    """Drop a target's override so it follows the global profit again."""
    if service not in TARGETS:
        return False
    ok = True
    for field in ("enabled", "mode", "percent", "fixed", "currency"):
        ok = _set(_svc_key(service, field), "0" if field == "enabled" else "") and ok
    return ok


def reset_all_markup():
    """Reset the global profit to defaults and clear every service/server override."""
    _set(K_MODE, DEFAULT_MARKUP_MODE)
    _set(K_PERCENT, DEFAULT_MARKUP_PERCENT)
    _set(K_FIXED, DEFAULT_MARKUP_FIXED)
    _set(K_CURRENCY, DEFAULT_MARKUP_CURRENCY)
    for service in TARGETS:
        reset_service_markup(service)
    return get_markup_config()


def service_profit_in_inr(real_price_inr, service):
    """Owner profit for one sale of `service`, in INR."""
    return profit_in_inr(real_price_inr, get_service_config(service))


def apply_service_markup(real_price_inr, service, minimum=1.0):
    """Real cost -> customer price (INR) using that service's profit rules."""
    return apply_markup(real_price_inr, get_service_config(service), minimum=minimum)


def apply_server_markup(real_price_inr, mode, minimum=1.0):
    """Real cost -> customer price (INR) for a *server* mode.

    Uses the server's own override when the owner enabled one.  When no
    server-specific override exists we fall back to the LZT / global rule so
    pricing keeps working exactly as before.
    """
    key = server_target_for_mode(mode)
    if key and is_service_override(key):
        return apply_markup(real_price_inr, get_service_config(key), minimum=minimum)
    return apply_service_markup(real_price_inr, "lzt", minimum=minimum)


def service_price_breakdown(real_price_inr, service):
    """Full INR + USDT + profit maths for one service."""
    return price_breakdown(real_price_inr, get_service_config(service))


def format_service_dual_price(real_price_inr, service, uid=None, currency=None):
    """Customer-facing price label for a service, in the user's currency."""
    if real_price_inr is None:
        return "—"
    try:
        float(real_price_inr)
    except (TypeError, ValueError):
        return "—"
    b = service_price_breakdown(real_price_inr, service)
    return format_user_amount(b["inr"], uid=uid, currency=currency)


def describe_service_markup(service):
    """One-line description of the profit rule used by a service."""
    cfg = get_service_config(service)
    if cfg["mode"] == "percent":
        text = f"{cfg['percent']:g}% profit"
    else:
        symbol = "₹" if cfg["currency"] == "INR" else "$"
        text = f"{symbol}{cfg['fixed']:g} fixed profit ({cfg['currency']})"
    return text + (" · custom" if cfg.get("override") else " · global")


def service_summary(service, samples=(10, 50, 100, 500)):
    """Rows for the admin live preview: cost -> profit -> INR -> USDT."""
    rows = []
    for cost in samples:
        b = service_price_breakdown(cost, service)
        rows.append({
            "cost": float(cost),
            "profit": b["profit_inr"],
            "inr": b["inr"],
            "usdt": b["usdt"],
        })
    return rows
