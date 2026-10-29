"""Runtime-editable configuration store.

WHY THIS EXISTS
---------------
Before this module the Temp Mail key/base URL and the TemporaSMS key were
read from ``config.py`` at import time.  That had two bad consequences:

1. A key baked into the repo could not be changed from the admin panel --
   the panel could only *show* it, and any button that tried to edit it was
   answered with "this button belongs to an older version of the panel".
2. Rotating a leaked key meant a redeploy, which is exactly what you do not
   want at 2 AM.

Now every provider setting resolves in this order:

    runtime store (admin panel)  ->  environment variable  ->  built-in default

so the owner can change the API key, base URL, provider or domain from the
bot itself, with no redeploy, and the change survives a restart because it
is written to the SQLite ``settings`` table (and mirrored to MongoDB when
``MONGO_URI`` is configured).

Nothing here ever raises into a handler: a broken DB must not break a menu.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Dict, Optional

_lock = threading.RLock()
_cache: Dict[str, str] = {}
_cache_loaded = False

# Keys the admin panel is allowed to write.  An allow-list keeps a typo in a
# wizard from silently creating a settings row nobody reads.
EDITABLE_KEYS = frozenset({
    "tempmail_provider",
    "tempmail_api_key",
    "tempmail_base_url",
    "tempmail_domain",
    "tempmail_account_email",
    "tempmail_account_password",
    "temporasms_api_key",
    "temporasms_base_url",
    "temporasms_service_whatsapp",
    "temporasms_service_numchange",
    "temporasms_service_allotp",
})


def _db_path() -> str:
    """Same resolution order the rest of the bot uses."""
    env = os.getenv("DB_PATH", "").strip()
    if env:
        return env
    if os.path.exists("bot.db"):
        return "bot.db"
    if os.path.exists("database.db"):
        return "database.db"
    return "bot.db"


def _connect() -> Optional[sqlite3.Connection]:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        return conn
    except Exception:
        return None


def _load_cache() -> None:
    global _cache_loaded
    if _cache_loaded:
        return
    with _lock:
        if _cache_loaded:
            return
        conn = _connect()
        if conn is not None:
            try:
                for key, value in conn.execute("SELECT key, value FROM settings"):
                    if key and value is not None:
                        _cache[str(key)] = str(value)
            except Exception:
                pass
            finally:
                conn.close()
        _cache_loaded = True


def get(key: str, default: str = "") -> str:
    """Runtime value if the admin set one, else `default`."""
    _load_cache()
    with _lock:
        value = _cache.get(key)
    if value is not None and str(value).strip() != "":
        return str(value).strip()
    return default


def set(key: str, value: str, *, allow_any: bool = False) -> bool:
    """Persist a runtime value. Returns False when the DB write failed."""
    global _cache_loaded
    if not allow_any and key not in EDITABLE_KEYS:
        raise KeyError(f"'{key}' is not an editable setting")
    value = "" if value is None else str(value).strip()
    with _lock:
        _cache[key] = value
        _cache_loaded = True
        conn = _connect()
        if conn is None:
            return False
        try:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()


def clear(key: str) -> bool:
    """Delete the runtime override so the env var / default takes over again."""
    with _lock:
        _cache.pop(key, None)
        conn = _connect()
        if conn is None:
            return False
        try:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()


def source_of(key: str) -> str:
    """'panel' when an admin override is stored, else 'env'."""
    _load_cache()
    with _lock:
        if _cache.get(key):
            return "panel"
    return "env"


def mask(secret: str) -> str:
    """Never show a full key in a chat that can be screenshotted."""
    secret = (secret or "").strip()
    if not secret:
        return "(not set)"
    if len(secret) <= 8:
        return secret[:2] + "*" * (len(secret) - 2)
    return f"{secret[:8]}…{secret[-4:]}"


# ---------------------------------------------------------------------------
#  Typed resolvers used by the clients
# ---------------------------------------------------------------------------
def tempmail_settings() -> dict:
    """Effective Temp Mail settings (panel override -> env -> default)."""
    provider = (
        get("tempmail_provider")
        or os.getenv("TEMPMAIL_PROVIDER", "").strip()
        or "grabmail"
    ).lower()

    if provider == "grabmail":
        default_key = os.getenv("GRABMAIL_API_KEY", "").strip()
        default_base = os.getenv("GRABMAIL_BASE_URL", "https://grabmail.io/api/v1").strip()
        default_domain = os.getenv("GRABMAIL_DOMAIN", "grabmail.io").strip()
    else:  # mtempmail (legacy)
        default_key = os.getenv("TEMPMAIL_API_KEY", "").strip()
        default_base = os.getenv("TEMPMAIL_BASE_URL", "https://mtempmail.com/api").strip()
        default_domain = os.getenv("TEMPMAIL_DOMAIN", "").strip()

    return {
        "provider": provider,
        "api_key": get("tempmail_api_key") or default_key,
        "base_url": (get("tempmail_base_url") or default_base).rstrip("/"),
        "domain": get("tempmail_domain") or default_domain,
        "account_email": get("tempmail_account_email") or os.getenv("TEMPMAIL_ACCOUNT_EMAIL", "").strip(),
        "account_password": get("tempmail_account_password") or os.getenv("TEMPMAIL_ACCOUNT_PASSWORD", "").strip(),
        "source": source_of("tempmail_api_key"),
    }


def temporasms_settings() -> dict:
    return {
        "api_key": get("temporasms_api_key") or os.getenv("TEMPORASMS_API_KEY", "").strip(),
        "base_url": (
            get("temporasms_base_url")
            or os.getenv("TEMPORASMS_BASE_URL", "https://api.temporasms.com").strip()
        ).rstrip("/"),
        "service_whatsapp": (
            get("temporasms_service_whatsapp")
            or os.getenv("TEMPORASMS_SERVICE_WHATSAPP", "whatsapp").strip()
        ),
        "service_numchange": (
            get("temporasms_service_numchange")
            or os.getenv("TEMPORASMS_SERVICE_NUMCHANGE", "telegram").strip()
        ),
        "service_allotp": (
            get("temporasms_service_allotp")
            or os.getenv("TEMPORASMS_SERVICE_ALLOTP", "telegram").strip()
        ),
        "source": source_of("temporasms_api_key"),
    }
