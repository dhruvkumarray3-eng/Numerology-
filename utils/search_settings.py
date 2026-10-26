"""Admin-controlled settings for the live LZT market search.

Everything the admin may want to tune lives here instead of being hard-coded
inside ``utils.lzt`` / ``plugins.buy``:

* whether live market search is enabled at all,
* which filter the **Good Quality** button uses,
* which filter the **Cheap** button uses,
* whether both buttons should show the cheap (spam-blocked) stock,
* the sort order per mode,
* how many results / pages to fetch,
* an optional price window (pmin/pmax in RUB),
* strict client-side spam verification.

Values are stored in the existing ``settings`` table (key/value), so they
survive restarts and can be changed from the admin panel without a redeploy.
"""

from database import cur, db

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
# Filter names map to the modes understood by ``LZTClient.search_items``:
#   nonspam  -> spam=no   (clean / good quality)
#   spam     -> spam=yes  (spam-blocked / cheap)
#   bulk     -> no spam filter
#   no_2fa / with_2fa / premium / no_email / with_email / dc5 / stars / aged
DEFAULTS = {
    "live_search_enabled": "1",
    "good_filter": "nonspam",
    "cheap_filter": "spam",
    # When ON, the "Good Quality" button also returns cheap stock.  This is the
    # behaviour the shop owner asked for: both buttons show the cheapest
    # available accounts, while the label stays the same.
    "both_cheap": "0",
    "good_order": "price_to_up",
    "cheap_order": "price_to_up",
    "bulk_order": "price_to_up",
    "max_results": "50",
    "max_pages": "4",
    "min_price": "",
    "max_price": "",
    # Drop items whose spam flag is known and does not match the requested
    # filter.  Keeps "Good" genuinely spam-free and "Cheap" genuinely cheap.
    "strict_spam": "1",
    # Show "(0)" next to countries in the picker.  Off by default because the
    # global cheap list only covers a few pages, so 0 usually means "unknown",
    # not "out of stock".
    "show_zero_counts": "0",
    # LZT's own search param: "Allow geo spam block in search with spam=no".
    # Without it, spam=no (Good Quality) hides every account that has a geo
    # spam block, which is a huge share of real stock -> empty lists.
    "allow_geo_spam": "1",
    # When a filtered search comes back empty, retry once with the spam /
    # price filters relaxed so the user sees real live accounts instead of
    # an empty "no stock" card.
    "auto_fallback": "1",
}

# Allowed values, used for validation and for cycling buttons in the panel.
VALID_FILTERS = [
    "nonspam", "spam", "bulk", "no_2fa", "with_2fa",
    "premium", "no_email", "with_email", "dc5", "stars", "aged",
]
VALID_ORDERS = [
    "price_to_up", "price_to_down", "pdate_to_down", "pdate_to_up",
]
VALID_LIMITS = ["20", "50", "100", "200"]
VALID_PAGES = ["1", "2", "3", "4", "6", "8"]

_BOOL_KEYS = {
    "live_search_enabled", "both_cheap", "strict_spam", "show_zero_counts",
    "allow_geo_spam", "auto_fallback",
}


def _raw_get(key):
    try:
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row and row[0] is not None:
            return str(row[0])
    except Exception:
        pass
    return DEFAULTS.get(key, "")


def get_search_setting(key):
    """Return a single setting as a string (never raises)."""
    if key not in DEFAULTS:
        return ""
    return _raw_get(key)


def set_search_setting(key, value):
    """Persist a single setting with light validation."""
    if key not in DEFAULTS:
        raise KeyError(f"Unknown search setting: {key}")

    value = "" if value is None else str(value).strip()

    if key in _BOOL_KEYS:
        value = "1" if value.lower() in ("1", "true", "yes", "on") else "0"
    elif key == "good_filter" or key == "cheap_filter":
        if value not in VALID_FILTERS:
            raise ValueError(f"Invalid filter: {value}")
    elif key in ("good_order", "cheap_order", "bulk_order"):
        if value not in VALID_ORDERS:
            raise ValueError(f"Invalid order: {value}")
    elif key == "max_results":
        if value not in VALID_LIMITS:
            raise ValueError(f"Invalid max_results: {value}")
    elif key == "max_pages":
        if value not in VALID_PAGES:
            raise ValueError(f"Invalid max_pages: {value}")
    elif key in ("min_price", "max_price"):
        if value:
            float(value)  # raises ValueError on garbage

    cur.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    db.commit()
    return value


def get_search_settings():
    """Return every search setting as a dict of strings."""
    return {key: _raw_get(key) for key in DEFAULTS}


def reset_search_settings():
    for key, value in DEFAULTS.items():
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    db.commit()


def is_live_search_enabled():
    return get_search_setting("live_search_enabled") == "1"


def is_both_cheap():
    return get_search_setting("both_cheap") == "1"


def is_strict_spam():
    return get_search_setting("strict_spam") == "1"


def show_zero_counts():
    """Whether the country picker should print "(0)" for empty countries."""
    return get_search_setting("show_zero_counts") == "1"


def allow_geo_spam():
    """Send ``allow_geo_spamblock=true`` with ``spam=no`` searches.

    LZT hides geo-spam-blocked accounts from ``spam=no`` unless this flag is
    set.  Those accounts are still perfectly usable, so leaving it off made
    the "Good Quality" list look empty for most countries.
    """
    return get_search_setting("allow_geo_spam") == "1"


def auto_fallback():
    """Retry a zero-result search with relaxed spam/price filters."""
    return get_search_setting("auto_fallback") == "1"


def resolve_mode(mode):
    """Map a UI mode to the filter actually sent to LZT.

    * ``nonspam`` ("Good Quality") uses ``good_filter``.
    * ``spam`` ("Cheap") uses ``cheap_filter``.
    * ``both_cheap`` forces the Good button onto the cheap filter.
    """
    mode = (mode or "bulk").strip().lower()

    if mode == "nonspam":
        if is_both_cheap():
            return get_search_setting("cheap_filter") or "spam"
        return get_search_setting("good_filter") or "nonspam"
    if mode == "spam":
        return get_search_setting("cheap_filter") or "spam"
    if mode == "bulk":
        return "bulk"
    return mode


def resolve_order(mode):
    mode = (mode or "bulk").strip().lower()
    # When "both cheap" is on, the Good button is really showing cheap stock,
    # so it must also use the cheap sort order.
    if mode == "nonspam" and is_both_cheap():
        mode = "spam"
    if mode == "nonspam":
        return get_search_setting("good_order") or "price_to_up"
    if mode == "spam":
        return get_search_setting("cheap_order") or "price_to_up"
    return get_search_setting("bulk_order") or "price_to_up"


def price_bounds():
    """Return (pmin, pmax) as floats or None."""
    def _f(key):
        raw = get_search_setting(key)
        if not raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return _f("min_price"), _f("max_price")


def int_setting(key, fallback):
    try:
        return int(get_search_setting(key))
    except (TypeError, ValueError):
        try:
            return int(DEFAULTS.get(key, fallback))
        except (TypeError, ValueError):
            return fallback


# ---------------------------------------------------------------------------
# Human-readable labels for the admin panel
# ---------------------------------------------------------------------------
FILTER_LABELS = {
    "nonspam": "🟢 Non-Spam (Good)",
    "spam": "🟡 Spam-Blocked (Cheap)",
    "bulk": "🌍 No Filter (All)",
    "no_2fa": "🔓 No 2FA",
    "with_2fa": "🔒 With 2FA",
    "premium": "💎 Premium",
    "no_email": "🚫 No Email",
    "with_email": "📧 With Email",
    "dc5": "🌐 DC 5",
    "stars": "⭐ Stars",
    "aged": "🏛 Aged",
}

ORDER_LABELS = {
    "price_to_up": "💰 Cheapest First",
    "price_to_down": "💎 Expensive First",
    "pdate_to_down": "🆕 Newest First",
    "pdate_to_up": "📜 Oldest First",
}
