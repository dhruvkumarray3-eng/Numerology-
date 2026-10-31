import sqlite3
import os
import math
import threading
from config import ADMIN_ID, SUPER_ADMINS, SUPPORT_URL, is_super_admin, logger

# Initialize DB
# ---------------------------------------------------------------------------
# The database must never be able to crash the boot.  A read-only volume, a
# corrupt file or a filesystem that rejects WAL (some container overlays do)
# used to raise straight out of this import and kill the process before any
# logging existed.  We now fall back gracefully instead.
# ---------------------------------------------------------------------------
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "otp_bot_final.db")


def _open_db(path: str) -> sqlite3.Connection:
    """Open ``path``, falling back to a writable temp file if needed."""
    conn = sqlite3.connect(path, check_same_thread=False, timeout=20)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except sqlite3.Error:
        # WAL is an optimisation, not a requirement.
        try:
            conn.execute("PRAGMA journal_mode=DELETE;")
        except sqlite3.Error:
            pass
    try:
        conn.execute("PRAGMA busy_timeout=20000;")
    except sqlite3.Error:
        pass
    return conn


try:
    _raw_db = _open_db(db_path)
except (sqlite3.Error, OSError) as exc:
    import tempfile

    fallback = os.path.join(tempfile.gettempdir(), "otp_bot_final.db")
    logger.error(
        "\u26a0\ufe0f Could not open %s (%s). Falling back to %s \u2014 data will "
        "not survive a restart; check the volume permissions.",
        db_path, exc, fallback,
    )
    db_path = fallback
    _raw_db = _open_db(fallback)


# ---------------------------------------------------------------------------
# Self-healing connection layer
# ---------------------------------------------------------------------------
# WHY: every plugin does ``from database import cur, db`` once at import time,
# so it keeps a hard reference to whatever object existed then.  If anything
# closes the underlying sqlite connection (a stray ``db.close()``, a module
# reload, a volume remount, or a plugin that shadows ``cur`` via
# ``from config import *``) every later query dies with
# ``sqlite3.ProgrammingError: Cannot operate on a closed database`` -- which is
# exactly what broke the UPI / Auto-UPI / IMAP admin screens.
#
# ``cur`` and ``db`` are therefore *proxies*: they always resolve to a live
# connection, reopening the file transparently when needed.  Existing code
# keeps working unchanged (``cur.execute(...).fetchone()``, ``cur.lastrowid``,
# ``db.commit()`` ...) because every attribute is forwarded to the real object.
# ---------------------------------------------------------------------------
_db_lock = threading.RLock()
_raw_cur = None
_db_gen = 0          # bumped every time the connection is (re)opened
_cur_gen = -1        # generation the cached cursor belongs to


def _live_conn():
    """Return a usable sqlite connection, reopening the file if it was closed."""
    global _raw_db, _db_gen
    with _db_lock:
        if _raw_db is not None:
            try:
                _raw_db.execute("SELECT 1")
                return _raw_db
            except Exception:
                pass  # closed / broken -> fall through and reopen
        try:
            _raw_db = _open_db(db_path)
            _db_gen += 1
            logger.warning("\u267b\ufe0f Database connection reopened (%s).", db_path)
        except Exception as exc:  # pragma: no cover - disk level failure
            logger.error("Database reopen failed: %s", exc)
        return _raw_db


def _live_cursor():
    """Return a cursor bound to the live connection (cached per generation)."""
    global _raw_cur, _cur_gen
    conn = _live_conn()
    with _db_lock:
        if conn is None:  # pragma: no cover - nothing we can do
            raise sqlite3.ProgrammingError("database unavailable")
        if _raw_cur is None or _cur_gen != _db_gen:
            _raw_cur = conn.cursor()
            _cur_gen = _db_gen
        return _raw_cur


class _SafeCursor:
    """Drop-in cursor proxy that never points at a closed connection."""

    __slots__ = ()

    def __getattr__(self, name):
        return getattr(_live_cursor(), name)

    def __iter__(self):
        return iter(_live_cursor())

    def __bool__(self):
        return True


class _SafeConnection:
    """Drop-in connection proxy that never points at a closed connection."""

    __slots__ = ()

    def __getattr__(self, name):
        return getattr(_live_conn(), name)

    def __bool__(self):
        return True


cur = _SafeCursor()
db = _SafeConnection()

def setup_db():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        referred_by INTEGER,
        total_deposited INTEGER DEFAULT 0,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        banned INTEGER DEFAULT 0,
        discount INTEGER DEFAULT 0,
        terms_accepted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS stock (
        phone TEXT PRIMARY KEY,
        session_file TEXT,
        country_name TEXT,
        country_icon TEXT DEFAULT '🌍',
        account_year INTEGER,
        category TEXT DEFAULT 'Good',
        price INTEGER,
        available INTEGER DEFAULT 1,
        twofa TEXT DEFAULT 'None',
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS auto_prices (
        country TEXT,
        year TEXT,
        price INTEGER,
        PRIMARY KEY (country, year)
    );
    CREATE TABLE IF NOT EXISTS spamfree_prices (
        country TEXT PRIMARY KEY,
        price INTEGER
    );
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method_name TEXT,
        status TEXT, 
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS upi_orders (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount INTEGER,
        status TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        country TEXT,
        year INTEGER,
        price INTEGER,
        phone TEXT,
        otp TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS custom_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        caption TEXT,
        qr_file_id TEXT
    );
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        p_add_stock INTEGER DEFAULT 0,
        p_manage_stock INTEGER DEFAULT 0,
        p_stats INTEGER DEFAULT 0,
        p_bal INTEGER DEFAULT 0,
        p_settings INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS custom_countries (
        code TEXT PRIMARY KEY,
        name TEXT,
        flag TEXT
    );
    CREATE TABLE IF NOT EXISTS smm_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        server INTEGER DEFAULT 1,
        service_id INTEGER,
        service_name TEXT,
        target_link TEXT,
        quantity INTEGER,
        price REAL,
        smm_order_id TEXT,
        status TEXT DEFAULT 'Pending',
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS source_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        price REAL,
        file_content TEXT,
        available INTEGER DEFAULT 1,
        stock INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS panels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        price REAL,
        panel_content TEXT,
        available INTEGER DEFAULT 1,
        stock INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS redeemed_transactions (
        email_msg_id TEXT PRIMARY KEY,
        utr TEXT,
        txn_id TEXT,
        amount REAL,
        user_id INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_redeemed_utr ON redeemed_transactions(utr);
    CREATE INDEX IF NOT EXISTS idx_redeemed_txn ON redeemed_transactions(txn_id);
    CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        amount REAL DEFAULT 0,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        expires_at TIMESTAMP,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS redeem_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        user_id INTEGER,
        amount REAL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Seed hardcoded Super Admin with full permissions
    for sa_id in SUPER_ADMINS:
        if sa_id:
            cur.execute("""
                INSERT OR REPLACE INTO admins (user_id, p_add_stock, p_manage_stock, p_stats, p_bal, p_settings)
                VALUES (?, 1, 1, 1, 1, 1)
            """, (sa_id,))
    db.commit()

# ---------------------------------------------------------------------------
# Seed the settings rows the admin panel *updates*.
# ---------------------------------------------------------------------------
# The panel used to write these with ``UPDATE ... WHERE key='x'``; when the row
# did not exist yet the UPDATE matched zero rows and the value was silently
# thrown away -- "Set USDT Rate", "Support URL", "Ref %" and the bot on/off
# switch all looked broken.  The writes are now upserts, and these defaults
# guarantee a readable value on a brand-new database too.
_DEFAULT_SETTINGS = {
    "bot_status": "on",
    "usdt_rate": "94",
    "ref_percent": "10",
    "support_url": "",
    "deposit_mode": "auto",
    "upi_id": "",
    "gmail_user": "",
    "gmail_pass": "",
}


def seed_default_settings():
    """Insert any missing default setting without overwriting a real value."""
    for key, value in _DEFAULT_SETTINGS.items():
        try:
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("could not seed setting %s: %s", key, exc)
    try:
        db.commit()
    except Exception:
        pass


def db_health():
    """Return a small dict describing the live connection (used at boot)."""
    try:
        cur.execute("SELECT 1").fetchone()
        return {"ok": True, "path": db_path}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "path": db_path, "error": str(exc)}


setup_db()
seed_default_settings()


def _migrate_catalog_stock():
    """Add explicit inventory counters; existing listings start at zero."""
    for table in ("source_codes", "panels"):
        columns = {row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        if "stock" not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN stock INTEGER NOT NULL DEFAULT 0")
    db.commit()


_migrate_catalog_stock()


def _migrate_remove_demo_catalog_items():
    """Remove only the exact example rows previously inserted by getters."""
    migration_key = "catalog_demo_seed_cleanup_v1"
    if cur.execute("SELECT 1 FROM settings WHERE key=?", (migration_key,)).fetchone():
        return

    demo_sources = [
        (
            "Main Store Bot (Full Modular Code)",
            "Complete full modular bot source code with OTP buying, SMM services, panels & instant delivery.",
            500.0,
            "https://github.com/dhruvkumarray3-eng/Numerology-",
        ),
        (
            "OTP & SMM Bot Source Code",
            "Complete Python Telethon based automated OTP & SMM bot source code.",
            299.0,
            "https://github.com/dhruvkumarray3-eng/Numerology-",
        ),
    ]
    demo_panels = [
        (
            "VIP SMM Panel (Server 1)",
            "High-speed VIP SMM reseller panel with instant order delivery and auto balance top-up.",
            399.0,
            "https://fathersmm.com",
        ),
        (
            "Budget SMM Panel (Server 2 - Cheap)",
            "Cheapest global SMM panel with over 1500+ bulk services and lowest wholesale rates.",
            399.0,
            "https://best-smm.com",
        ),
    ]
    for row in demo_sources:
        cur.execute(
            "DELETE FROM source_codes WHERE title=? AND description=? AND price=? AND file_content=?",
            row,
        )
    for row in demo_panels:
        cur.execute(
            "DELETE FROM panels WHERE title=? AND description=? AND price=? AND panel_content=?",
            row,
        )
    cur.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, 'done')",
        (migration_key,),
    )
    db.commit()


_migrate_remove_demo_catalog_items()

# --- Lightweight migrations: add per-user preferences if missing ---
def _migrate_user_prefs():
    try:
        cols = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
        if "currency" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN currency TEXT DEFAULT 'INR'")
        if "language" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'en'")
        # Remembers that the bottom reply keyboard was already sent, so the
        # tiny carrier message is not re-sent on every /start.
        if "menu_installed" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN menu_installed INTEGER DEFAULT 0")
        db.commit()
    except Exception as e:
        logger.warning(f"User prefs migration skipped: {e}")

    # Reply-keyboard version.  Telegram keeps the old keyboard on the user's
    # screen until the bot sends a new one, so we must be able to tell when a
    # user is still holding a stale layout (that is what kept "Profile" dead:
    # the old label used U+2119 which the fold map did not recognise).
    try:
        cur.execute("SELECT menu_version FROM users LIMIT 1")
    except Exception:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN menu_version INTEGER DEFAULT 0")
        except Exception:
            pass
        db.commit()
    except Exception as e:
        logger.warning(f"User prefs migration skipped: {e}")

_migrate_user_prefs()

def is_menu_installed(uid):
    """True if the reply keyboard carrier was already sent to this user."""
    try:
        row = cur.execute("SELECT menu_installed FROM users WHERE user_id=?", (uid,)).fetchone()
        return bool(row and row[0])
    except Exception:
        return False

def set_menu_installed(uid, flag=1):
    """Remember / forget that the reply keyboard is installed for this user."""
    try:
        cur.execute("UPDATE users SET menu_installed=? WHERE user_id=?", (1 if flag else 0, uid))
        db.commit()
    except Exception as e:
        logger.warning(f"Could not persist menu_installed for {uid}: {e}")

def get_menu_version(uid):
    """Stored reply-keyboard version for this user (0 = never installed)."""
    try:
        row = cur.execute("SELECT menu_version FROM users WHERE user_id=?", (uid,)).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def set_menu_version(uid, version):
    """Remember which keyboard layout version this user is holding."""
    try:
        cur.execute("UPDATE users SET menu_version=? WHERE user_id=?", (int(version), uid))
        db.commit()
    except Exception as e:
        logger.warning(f"Could not persist menu_version for {uid}: {e}")


def get_user_currency(uid):
    try:
        row = cur.execute("SELECT currency FROM users WHERE user_id=?", (uid,)).fetchone()
        return (row[0] if row and row[0] else "INR").upper()
    except Exception:
        return "INR"

def set_user_currency(uid, currency):
    cur.execute("UPDATE users SET currency=? WHERE user_id=?", (str(currency).upper(), uid))
    db.commit()

def get_user_language(uid):
    try:
        row = cur.execute("SELECT language FROM users WHERE user_id=?", (uid,)).fetchone()
        return (row[0] if row and row[0] else "en").lower()
    except Exception:
        return "en"

def set_user_language(uid, language):
    cur.execute("UPDATE users SET language=? WHERE user_id=?", (str(language).lower(), uid))
    db.commit()

# ================= HELPER FUNCTIONS =================
def is_bot_online():
    res = cur.execute("SELECT value FROM settings WHERE key='bot_status'").fetchone()
    return res[0] == 'on' if res else True

def is_admin(uid):
    if is_super_admin(uid): return True
    row = cur.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row)

def has_perm(uid, perm):
    if is_super_admin(uid): return True
    row = cur.execute(f"SELECT {perm} FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0] == 1)

def ensure_user(uid):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    db.commit()

def get_usdt_rate():
    res = cur.execute("SELECT value FROM settings WHERE key='usdt_rate'").fetchone()
    try: return float(res[0]) if res else 94.0
    except: return 94.0

def get_support_url():
    res = cur.execute("SELECT value FROM settings WHERE key='support_url'").fetchone()
    url = res[0] if res and res[0] else SUPPORT_URL
    if not url.startswith("http"): url = "https://" + url.replace("@", "t.me/")
    return url

def to_usd(inr):
    return round(inr / get_usdt_rate(), 2)

def is_user_banned(uid):
    res = cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
    return res and res[0] == 1

def update_balance(uid, amount):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    db.commit()

COUNTRY_CODES = {
    '1': ('USA/Canada', '🇺🇸'), '7': ('Russia', '🇷🇺'), '20': ('Egypt', '🇪🇬'),
    '27': ('South Africa', '🇿🇦'), '31': ('Netherlands', '🇳🇱'), '32': ('Belgium', '🇧🇪'),
    '33': ('France', '🇫🇷'), '34': ('Spain', '🇪🇸'), '39': ('Italy', '🇮🇹'), 
    '44': ('UK', '🇬🇧'), '46': ('Sweden', '🇸🇪'), '48': ('Poland', '🇵🇱'),
    '49': ('Germany', '🇩🇪'), '51': ('Peru', '🇵🇪'), '52': ('Mexico', '🇲🇽'),
    '54': ('Argentina', '🇦🇷'), '55': ('Brazil', '🇧🇷'), '56': ('Chile', '🇨🇱'),
    '57': ('Colombia', '🇨🇴'), '58': ('Venezuela', '🇻🇪'), '60': ('Malaysia', '🇲🇾'),
    '61': ('Australia', '🇦🇺'), '62': ('Indonesia', '🇮🇩'), '63': ('Philippines', '🇵🇭'), 
    '66': ('Thailand', '🇹🇭'), '84': ('Vietnam', '🇻🇳'), '86': ('China', '🇨🇳'), 
    '90': ('Turkey', '🇹🇷'), '91': ('India', '🇮🇳'), '92': ('Pakistan', '🇵🇰'), 
    '93': ('Afghanistan', '🇦🇫'), '94': ('Sri Lanka', '🇱🇰'), '95': ('Myanmar', '🇲🇲'),
    '98': ('Iran', '🇮🇷'), '212': ('Morocco', '🇲🇦'), '213': ('Algeria', '🇩🇿'),
    '234': ('Nigeria', '🇳🇬'), '254': ('Kenya', '🇰🇪'), '255': ('Tanzania', '🇹🇿'),
    '380': ('Ukraine', '🇺🇦'), '880': ('Bangladesh', '🇧🇩'), '964': ('Iraq', '🇮🇶'),
    '966': ('Saudi Arabia', '🇸🇦'), '971': ('UAE', '🇦🇪'), '998': ('Uzbekistan', '🇺🇿')
}

def get_flag_by_country_name(name):
    for code, (c_name, c_flag) in COUNTRY_CODES.items():
        if c_name == name: return c_flag
    try:
        row = cur.execute("SELECT flag FROM custom_countries WHERE name=?", (name,)).fetchone()
        if row: return row[0]
    except: pass
    # Robust fallback: resolve ISO codes, slugs, dial codes and aliases.
    try:
        from utils.flags import flag_for
        flag = flag_for(name)
        if flag and flag != "🌍":
            return flag
    except Exception:
        pass
    return "🌍"

def get_country_info(phone):
    phone = str(phone).replace(' ', '').replace('+', '')
    if not phone: return "Unknown", "🌍"
    
    try:
        customs = cur.execute("SELECT code, name, flag FROM custom_countries").fetchall()
        customs.sort(key=lambda x: len(x[0]), reverse=True)
        for code, name, flag in customs:
            if phone.startswith(code): return name, flag
    except: pass

    for length in (3, 2, 1):
        prefix = phone[:length]
        if prefix in COUNTRY_CODES: return COUNTRY_CODES[prefix]
    return "Unknown", "🌍"

def get_bot_mode():
    res = cur.execute("SELECT value FROM settings WHERE key='bot_mode'").fetchone()
    if res and res[0] in ('manual', 'panel', 'hybrid'):
        return res[0]
    return os.getenv("BOT_MODE", "manual").strip().lower()

def set_bot_mode(mode):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('bot_mode', ?)", (mode,))
    db.commit()

def get_lzt_key():
    res = cur.execute("SELECT value FROM settings WHERE key='lzt_api_key'").fetchone()
    if res and res[0]:
        return res[0].strip()
    return os.getenv("LZT_API_KEY", "").strip()

def set_lzt_key(key):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('lzt_api_key', ?)", (key.strip(),))
    db.commit()

def get_rub_rate():
    res = cur.execute("SELECT value FROM settings WHERE key='rub_rate'").fetchone()
    if res and res[0]:
        try: return float(res[0])
        except: pass
    try: return float(os.getenv("RUB_RATE", "1.15"))
    except: return 1.15

def set_rub_rate(rate):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('rub_rate', ?)", (str(rate),))
    db.commit()

def get_lzt_margin():
    res = cur.execute("SELECT value FROM settings WHERE key='lzt_margin'").fetchone()
    if res and res[0] is not None:
        try:
            margin = float(res[0])
            if math.isfinite(margin) and margin >= 0:
                return margin
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        margin = float(os.getenv("LZT_MARGIN", "25.0"))
    except (TypeError, ValueError, OverflowError):
        return 25.0
    return margin if math.isfinite(margin) and margin >= 0 else 25.0

def set_lzt_margin(margin):
    try:
        margin = float(margin)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("LZT margin must be a finite, non-negative amount") from exc
    if not math.isfinite(margin) or margin < 0:
        raise ValueError("LZT margin must be a finite, non-negative amount")
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('lzt_margin', ?)", (str(margin),))
    db.commit()

def adjust_price_by_mode(base_val, mode):
    if mode == 'spam':
        # Spam accounts discounted (~45% off, cheap for channel joiners while keeping profit 100% safe)
        return max(int(base_val * 0.55), 15)
    elif mode == 'nonspam':
        # Non-spam / clean accounts priced higher for guaranteed 100% spam-free quality
        return max(int(round(base_val * 1.25)), base_val + 8)
    elif mode == 'premium':
        return base_val + 150
    return base_val

def _apply_owner_margin(real_cost_inr, mode=None):
    """Panel real cost (INR) -> owner's selling price (INR).

    Honours the unified profit engine:
      * percent mode  -> cost + N%
      * fixed mode    -> cost + fixed INR/USD amount

    When a ``mode`` (bulk / nonspam / numchange / spam) is supplied and the
    owner enabled a per-server override for it, that server's rule wins.
    Otherwise the LZT/global rule is used.  Falls back to the legacy per-item
    LZT margin if the engine is unavailable, so pricing can never break.
    """
    try:
        from utils.markup import (
            apply_service_markup, apply_server_markup, get_service_config,
            is_service_override, server_target_for_mode,
        )
        srv_key = server_target_for_mode(mode) if mode else None
        if srv_key and is_service_override(srv_key):
            return apply_server_markup(real_cost_inr, mode)
        cfg = get_service_config("lzt")
        # Honour the configured mode even when the fixed amount is 0.
        if cfg.get("mode") in ("percent", "fixed"):
            return apply_service_markup(real_cost_inr, "lzt")
    except Exception:
        pass
    try:
        margin = get_lzt_margin()
    except Exception:
        margin = 0
    return max(int(round(float(real_cost_inr) + float(margin))), 25)


def get_panel_price(country, year, lzt_price_rub=0, mode='bulk'):
    # Aged year price additions (if no explicit year price is set)
    YEAR_ADDITIONS = {
        2026: 0,
        2025: 25,
        2024: 55,
        2023: 85,
        2022: 125,
        2021: 175,
        2020: 230,
        2019: 290,
        2018: 350,
        2017: 420
    }

    try: y_int = int(year)
    except: y_int = 2026

    add_amount = YEAR_ADDITIONS.get(y_int, 0 if y_int >= 2026 else (2026 - y_int) * 60)

    # 1. SPAM-FREE (NON-SPAM) MODE:
    # Uses the fresh VIP Spam-Free price list directly!
    if mode == 'nonspam':
        row = cur.execute("SELECT price FROM spamfree_prices WHERE country=?", (country,)).fetchone()
        if row and row[0] and row[0] > 0:
            return int(row[0]) + add_amount

    # 2. SPAM / USED MODE:
    # Retain the previous cheap pricing from base auto_prices table
    if mode == 'spam':
        row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=?", (country, str(year))).fetchone()
        if not row:
            row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year IN ('Common', 'ALL')", (country,)).fetchone()
        
        if row and row[0] and row[0] > 0:
            base = int(row[0])
            total = base + add_amount
            return max(int(total * 0.55), 15)
        
        # Dynamic fallback if no auto_price row.
        # Spam accounts are already the cheapest items on LZT, so we do NOT
        # apply an extra discount on top of the owner markup.
        rub_rate = get_rub_rate()
        inr_cost = lzt_price_rub * rub_rate
        return max(int(round(_apply_owner_margin(inr_cost, mode))), 15)

    # 3. Check if admin has set explicit custom price in auto_prices table for this specific (country, year)
    row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=?", (country, str(year))).fetchone()
    if row and row[0] and row[0] > 0:
        base = int(row[0])
        return adjust_price_by_mode(base, mode)
    
    # 4. Get base country price (set with year='Common' or 'ALL')
    row_all = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year IN ('Common', 'ALL')", (country,)).fetchone()
    base_price = int(row_all[0]) if (row_all and row_all[0] and row_all[0] > 0) else None

    if base_price is not None:
        total = base_price + add_amount
        return adjust_price_by_mode(total, mode)
        
    # 5. Dynamic calculation from LZT RUB price if no base price is found.
    # The owner markup is applied exactly ONCE here:
    #     user_price = panel_cost_inr + owner_markup
    # e.g. panel ₹15 + ₹24 markup = ₹39 shown to the user.
    # No extra mode multipliers are applied so the maths stays predictable.
    rub_rate = get_rub_rate()
    inr_cost = lzt_price_rub * rub_rate
    return max(int(round(_apply_owner_margin(inr_cost, mode))), 1)

def get_change_number_fee():
    res = cur.execute("SELECT value FROM settings WHERE key='change_number_fee'").fetchone()
    try:
        return int(res[0]) if res and res[0] is not None else 10
    except:
        return 10

def set_change_number_fee(fee):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('change_number_fee', ?)", (str(fee),))
    db.commit()

def get_fsub_status():
    res = cur.execute("SELECT value FROM settings WHERE key='fsub_status'").fetchone()
    return res[0].strip().lower() if res and res[0] else 'on'

def set_fsub_status(status):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fsub_status', ?)", (str(status).strip().lower(),))
    db.commit()

def get_fsub_channels():
    res = cur.execute("SELECT value FROM settings WHERE key='fsub_channels'").fetchone()
    if res and res[0] is not None:
        val = res[0].strip()
        if not val: return []
        return [c.strip() for c in val.split(",") if c.strip()]
    raw = os.getenv("CHECK_CHANNELS", "")
    return [c.strip() for c in raw.split(",") if c.strip()]

def get_fsub_urls():
    from utils.helpers import format_join_url
    res = cur.execute("SELECT value FROM settings WHERE key='fsub_urls'").fetchone()
    if res and res[0] is not None:
        val = res[0].strip()
        if not val: return []
        return [format_join_url(u) for u in val.split(",") if u.strip()]
    raw = os.getenv("JOIN_URLS", "")
    return [format_join_url(u) for u in raw.split(",") if u.strip()]

def set_fsub_data(channels_list, urls_list):
    from utils.helpers import format_join_url
    ch_str = ",".join([str(c).strip() for c in channels_list if str(c).strip()])
    url_str = ",".join([format_join_url(u) for u in urls_list if format_join_url(u)])
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fsub_channels', ?)", (ch_str,))
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fsub_urls', ?)", (url_str,))
    db.commit()

def add_fsub_channel(channel_id, join_url):
    from utils.helpers import format_join_url
    chs = get_fsub_channels()
    urls = get_fsub_urls()
    ch_str = str(channel_id).strip()
    norm_url = format_join_url(join_url)
    
    if ch_str in chs:
        idx = chs.index(ch_str)
        if idx < len(urls):
            urls[idx] = norm_url
        else:
            urls.append(norm_url)
    else:
        chs.append(ch_str)
        urls.append(norm_url)
        
    set_fsub_data(chs, urls)

def remove_fsub_channel(index):
    chs = get_fsub_channels()
    urls = get_fsub_urls()
    if 0 <= index < len(chs):
        chs.pop(index)
        if index < len(urls):
            urls.pop(index)
        set_fsub_data(chs, urls)

def get_log_channels_db():
    res = cur.execute("SELECT value FROM settings WHERE key='log_channels'").fetchone()
    if res and res[0] is not None:
        val = res[0].strip()
        if not val: return []
        out = []
        for c in val.split(","):
            c = c.strip()
            if c:
                try: out.append(int(c))
                except: out.append(c)
        return out
    from config import LOG_CHANNELS
    return LOG_CHANNELS

def set_log_channels_db(channels_list):
    ch_str = ",".join([str(c).strip() for c in channels_list if str(c).strip()])
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_channels', ?)", (ch_str,))
    db.commit()

def add_log_channel_db(channel_id):
    chs = get_log_channels_db()
    c_str = str(channel_id).strip()
    try: val = int(c_str)
    except: val = c_str
    if val not in chs:
        chs.append(val)
        set_log_channels_db(chs)

def remove_log_channel_db(channel_id):
    chs = get_log_channels_db()
    c_str = str(channel_id).strip()
    chs = [c for c in chs if str(c) != c_str]
    set_log_channels_db(chs)

# ---------------------------------------------------------
# OFFICIAL LINKS MIGRATION
# ---------------------------------------------------------
# The bot ships with one official support group, one owner contact,
# one logger channel and one main network channel. Older deployments may
# still have different values stored in the settings table, so this runs
# once and force-aligns them with config.py.
LINKS_MIGRATION_KEY = "official_links_v2"


def apply_official_links_migration(force=False):
    """Force-align support / owner / logger / force-join links with config.py.

    Runs only once per database unless ``force=True`` is passed.
    Returns True when values were written, False when already applied.
    """
    try:
        if not force:
            done = cur.execute(
                "SELECT value FROM settings WHERE key=?", (LINKS_MIGRATION_KEY,)
            ).fetchone()
            if done and str(done[0]).strip() == "done":
                return False

        from config import (
            CHECK_CHANNELS,
            JOIN_URLS,
            LOG_CHANNEL_ID,
            SUPPORT_URL,
            OWNER_URL,
            UPDATES_URL,
        )

        channels = [c for c in (CHECK_CHANNELS or []) if str(c).strip()]
        urls = [u for u in (JOIN_URLS or []) if str(u).strip()]

        set_fsub_data(channels, urls)
        set_fsub_status("on")

        log_ids = [LOG_CHANNEL_ID] if LOG_CHANNEL_ID else []
        set_log_channels_db(log_ids)

        for key, value in (
            ("support_url", SUPPORT_URL),
            ("owner_url", OWNER_URL),
            ("updates_url", UPDATES_URL),
        ):
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (LINKS_MIGRATION_KEY, "done"),
        )
        db.commit()
        logger.info(
            "\u2705 Official links applied: support=%s owner=%s logger=%s join=%s",
            SUPPORT_URL, OWNER_URL, LOG_CHANNEL_ID, urls,
        )
        return True
    except Exception as exc:  # never break startup
        logger.warning(f"\u26a0\ufe0f Official links migration skipped: {exc}")
        return False


def get_start_image_url():
    res = cur.execute("SELECT value FROM settings WHERE key='start_image'").fetchone()
    if res and res[0]:
        url = res[0].strip()
        # Migrate the old placeholder away automatically.
        if "yukiapi.site" in url:
            return "https://files.catbox.moe/hjj2jd.png"
        return url
    return "https://files.catbox.moe/hjj2jd.png"

def set_start_image_url(url):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('start_image', ?)", (url.strip(),))
    db.commit()


# --------------------------------------------------------------------------
# Owner-editable payment settings (Trust Wallet / USDT + UPI)
# --------------------------------------------------------------------------
def _get_setting(key):
    try:
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


def _set_setting(key, value):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value).strip()))
    db.commit()


def get_trust_wallet_address():
    """Owner-set USDT (BEP-20) address, falling back to env config."""
    from config import TRUST_WALLET_ADDRESS, BEP20_ADDRESS
    return (_get_setting("trust_wallet_address")
            or (TRUST_WALLET_ADDRESS or "").strip()
            or (BEP20_ADDRESS or "").strip())


def set_trust_wallet_address(addr):
    _set_setting("trust_wallet_address", addr)


def get_trust_wallet_qr():
    """Owner-set QR (URL or Telegram file id), falling back to env config."""
    from config import TRUST_WALLET_QR
    return _get_setting("trust_wallet_qr") or (TRUST_WALLET_QR or "").strip()


def set_trust_wallet_qr(value):
    _set_setting("trust_wallet_qr", value)


def get_upi_id():
    """Owner-set UPI id, falling back to env config."""
    from config import UPI_ID
    return _get_setting("upi_id") or (UPI_ID or "").strip()


def set_upi_id(value):
    _set_setting("upi_id", value)

def get_source_codes():
    return cur.execute(
        "SELECT id, title, description, price, file_content, available, stock "
        "FROM source_codes WHERE available=1 ORDER BY id DESC"
    ).fetchall()

def get_panels():
    # Cheapest-first so users always see the lowest rates first.
    return cur.execute(
        "SELECT id, title, description, price, panel_content, available, stock "
        "FROM panels WHERE available=1 ORDER BY price ASC, id DESC"
    ).fetchall()

def is_payment_redeemed_db(email_msg_id=None, utr=None, txn_id=None):
    if email_msg_id and str(email_msg_id).strip():
        r = cur.execute("SELECT 1 FROM redeemed_transactions WHERE email_msg_id=?", (str(email_msg_id).strip(),)).fetchone()
        if r: return True
    if utr and str(utr).strip():
        u_str = str(utr).strip()
        r = cur.execute("SELECT 1 FROM redeemed_transactions WHERE utr=?", (u_str,)).fetchone()
        if r: return True
        r = cur.execute("SELECT 1 FROM deposits WHERE utr=? AND status='approved'", (u_str,)).fetchone()
        if r: return True
    if txn_id and str(txn_id).strip():
        t_str = str(txn_id).strip()
        r = cur.execute("SELECT 1 FROM redeemed_transactions WHERE txn_id=?", (t_str,)).fetchone()
        if r: return True
        r = cur.execute("SELECT 1 FROM deposits WHERE utr=? AND status='approved'", (t_str,)).fetchone()
        if r: return True
    return False

def record_redeemed_payment_db(email_msg_id, utr, txn_id, amount, user_id):
    try:
        cur.execute("""
            INSERT OR REPLACE INTO redeemed_transactions (email_msg_id, utr, txn_id, amount, user_id)
            VALUES (?, ?, ?, ?, ?)
        """, (email_msg_id or "", utr or "", txn_id or "", amount, user_id))
        db.commit()
    except Exception as e:
        logger.error(f"Error recording redeemed payment: {e}")


# ================= REDEEM CODE HELPERS =================
def create_redeem_code(code, amount, max_uses=1, expires_at=None):
    cur.execute(
        "INSERT OR REPLACE INTO redeem_codes (code, amount, max_uses, used_count, expires_at, active) VALUES (?, ?, ?, 0, ?, 1)",
        (str(code).strip(), float(amount), int(max_uses), expires_at),
    )
    db.commit()


def redeem_code_for_user(code, user_id):
    """Redeems a code atomically. Returns (ok, message, amount)."""
    code = str(code or "").strip()
    if not code:
        return False, "Please enter a valid code.", 0.0
    row = cur.execute(
        "SELECT code, amount, max_uses, used_count, expires_at, active FROM redeem_codes WHERE code=?",
        (code,),
    ).fetchone()
    if not row:
        return False, "❌ Invalid or unknown redeem code.", 0.0
    _, amount, max_uses, used_count, expires_at, active = row
    if not active:
        return False, "❌ This code is no longer active.", 0.0
    if max_uses and used_count >= max_uses:
        return False, "❌ This code has already been fully redeemed.", 0.0
    if expires_at:
        try:
            import datetime as _dt
            exp = _dt.datetime.fromisoformat(str(expires_at))
            # datetime.utcnow() is deprecated (3.12+) and warns on Python 3.14.
            # Compare with an explicit UTC-aware value; treat naive as UTC.
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_dt.timezone.utc)
            if _dt.datetime.now(_dt.timezone.utc) > exp:
                return False, "❌ This code has expired.", 0.0
        except Exception:
            pass
    already = cur.execute(
        "SELECT 1 FROM redeem_log WHERE code=? AND user_id=?", (code, user_id)
    ).fetchone()
    if already:
        return False, "❌ You have already redeemed this code.", 0.0
    cur.execute("UPDATE redeem_codes SET used_count = used_count + 1 WHERE code=?", (code,))
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (float(amount), user_id))
    cur.execute(
        "INSERT INTO redeem_log (code, user_id, amount) VALUES (?, ?, ?)",
        (code, user_id, float(amount)),
    )
    db.commit()
    return True, "✅ Code redeemed successfully!", float(amount)


def list_redeem_codes():
    return cur.execute(
        "SELECT code, amount, max_uses, used_count, active FROM redeem_codes ORDER BY rowid DESC"
    ).fetchall()


def clear_legacy_stock_once():
    """One-time cleanup of the old auto-imported stock.

    The bot used to ship a large pool of stale Telethon sessions.  On the
    first start after this update we wipe that legacy pool exactly once and
    record a flag so newly added stock is never touched again.  Manual
    "Basic Telegram Account" stock lives in a separate table and is safe.
    """
    try:
        row = cur.execute(
            "SELECT value FROM settings WHERE key='legacy_stock_cleared'"
        ).fetchone()
        if row:
            return 0
        removed = cur.execute("SELECT COUNT(*) FROM stock").fetchone()[0]
        cur.execute("DELETE FROM stock")
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('legacy_stock_cleared', '1')"
        )
        db.commit()
        if removed:
            logger.info(f"Legacy stock cleared once: {removed} row(s) removed.")
        return int(removed or 0)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"legacy stock cleanup skipped: {exc}")
        return 0


try:
    clear_legacy_stock_once()
except Exception:
    pass
