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


def format_dual_price(real_price_inr, config=None):
    """The user-facing label: '₹1,299 · 14.76 USDT'.

    Returns an em-dash when the price is unknown/invalid so callers never show
    a misleading '₹1' for a country that simply has no live price.
    """
    if real_price_inr is None:
        return "—"
    try:
        float(real_price_inr)
    except (TypeError, ValueError):
        return "—"
    b = price_breakdown(real_price_inr, config)
    return f"{format_inr(b['inr'])} · {format_usdt(b['usdt'])}"


def format_dual_from_inr(amount_inr):
    """Dual label when the INR amount is already the final selling price."""
    try:
        inr = max(0.0, float(amount_inr))
    except (TypeError, ValueError):
        inr = 0.0
    return f"{format_inr(inr)} · {format_usdt(usdt_from_inr(inr))}"
