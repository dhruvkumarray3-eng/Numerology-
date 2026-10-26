import sqlite3
import os
import math
from config import ADMIN_ID, SUPER_ADMINS, SUPPORT_URL, is_super_admin, logger

# Initialize DB
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "otp_bot_final.db")
db = sqlite3.connect(db_path, check_same_thread=False, timeout=20)
db.execute("PRAGMA journal_mode=WAL;")
cur = db.cursor()

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
        available INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS panels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        price REAL,
        panel_content TEXT,
        available INTEGER DEFAULT 1
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

setup_db()

# --- Lightweight migrations: add per-user preferences if missing ---
def _migrate_user_prefs():
    try:
        cols = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
        if "currency" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN currency TEXT DEFAULT 'INR'")
        if "language" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'en'")
        db.commit()
    except Exception as e:
        logger.warning(f"User prefs migration skipped: {e}")

_migrate_user_prefs()

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
        
        # Dynamic fallback if no auto_price row
        rub_rate = get_rub_rate()
        margin = get_lzt_margin()
        inr_cost = lzt_price_rub * rub_rate
        calculated = round(inr_cost + margin)
        final_p = max(int(calculated), 25)
        return max(int(final_p * 0.55), 15)

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
        
    # 5. Dynamic calculation from LZT RUB price if no base price is found
    rub_rate = get_rub_rate()
    margin = get_lzt_margin()
    inr_cost = lzt_price_rub * rub_rate
    calculated = round(inr_cost + margin)
    final_p = max(int(calculated), 25)
    return adjust_price_by_mode(final_p, mode)

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
        return res[0].strip()
    return "https://yukiapi.site/file/0z3Q9oA9"

def set_start_image_url(url):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('start_image', ?)", (url.strip(),))
    db.commit()

def get_source_codes():
    rows = cur.execute("SELECT id, title, description, price, file_content, available FROM source_codes WHERE available=1").fetchall()
    if not rows:
        defaults = [
            ("Main Store Bot (Full Modular Code)", "Complete full modular bot source code with OTP buying, SMM services, panels & instant delivery.", 500.0, "https://github.com/dhruvkumarray3-eng/Numerology-"),
            ("OTP & SMM Bot Source Code", "Complete Python Telethon based automated OTP & SMM bot source code.", 299.0, "https://github.com/dhruvkumarray3-eng/Numerology-")
        ]
        for t, d, p, f in defaults:
            cur.execute("INSERT INTO source_codes (title, description, price, file_content) VALUES (?,?,?,?)", (t, d, p, f))
        db.commit()
        rows = cur.execute("SELECT id, title, description, price, file_content, available FROM source_codes WHERE available=1").fetchall()
    return rows

def get_panels():
    # Cheapest-first so users always see the lowest rates first.
    rows = cur.execute("SELECT id, title, description, price, panel_content, available FROM panels WHERE available=1 ORDER BY price ASC").fetchall()
    if not rows:
        defaults = [
            ("VIP SMM Panel (Server 1)", "High-speed VIP SMM reseller panel with instant order delivery and auto balance top-up.", 399.0, "https://fathersmm.com"),
            ("Budget SMM Panel (Server 2 - Cheap)", "Cheapest global SMM panel with over 1500+ bulk services and lowest wholesale rates.", 399.0, "https://best-smm.com")
        ]
        for t, d, p, f in defaults:
            cur.execute("INSERT INTO panels (title, description, price, panel_content) VALUES (?,?,?,?)", (t, d, p, f))
        db.commit()
        rows = cur.execute("SELECT id, title, description, price, panel_content, available FROM panels WHERE available=1 ORDER BY price ASC").fetchall()
    return rows

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
            if _dt.datetime.utcnow() > exp:
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
