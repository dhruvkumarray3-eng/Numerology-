"""MongoDB storage layer.

Every meaningful action (order, deposit, redeem, session generation, panel
purchase, admin change, plain event) is written to MongoDB so the owner can
pull a complete history for any user id.

Design rules:
  * MongoDB is OPTIONAL. If `MONGO_URI` is not set the module silently
    no-ops and the bot keeps running on SQLite exactly as before.
  * Nothing in this module ever raises into the bot. All failures are logged
    and swallowed.
  * Writes are fire-and-forget on a small thread pool so they never block the
    Telegram event loop.
"""
import asyncio
import datetime
import threading

from config import MONGO_URI, MONGO_DB, logger

_lock = threading.Lock()
_client = None
_db = None
_failed = False

COLLECTIONS = (
    "users",
    "orders",
    "deposits",
    "redeems",
    "sessions",
    "panel_orders",
    "events",
)


def mongo_enabled() -> bool:
    """True only when a URI is configured and the driver is installed."""
    if not MONGO_URI or _failed:
        return False
    try:
        import pymongo  # noqa: F401
    except Exception:
        return False
    return True


def _get_db():
    global _client, _db, _failed
    if _db is not None:
        return _db
    if not mongo_enabled():
        return None
    with _lock:
        if _db is not None:
            return _db
        try:
            from pymongo import MongoClient

            _client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=4000,
                connectTimeoutMS=4000,
                socketTimeoutMS=6000,
                maxPoolSize=10,
                tz_aware=True,
            )
            _client.admin.command("ping")
            _db = _client[MONGO_DB]
            # Helpful indexes for the /history lookup.
            try:
                _db.events.create_index([("user_id", 1), ("created_at", -1)])
                _db.orders.create_index([("user_id", 1), ("created_at", -1)])
                _db.panel_orders.create_index([("user_id", 1), ("created_at", -1)])
                _db.deposits.create_index([("user_id", 1), ("created_at", -1)])
                _db.redeems.create_index([("user_id", 1), ("created_at", -1)])
                _db.sessions.create_index([("user_id", 1), ("created_at", -1)])
            except Exception:
                pass
            logger.info(f"MongoDB connected -> db='{MONGO_DB}'")
        except Exception as exc:
            _failed = True
            logger.warning(f"MongoDB unavailable, continuing on SQLite only: {exc}")
            return None
    return _db


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _insert(collection: str, doc: dict):
    db = _get_db()
    if db is None:
        return False
    try:
        doc.setdefault("created_at", _now())
        db[collection].insert_one(doc)
        return True
    except Exception as exc:
        logger.warning(f"Mongo insert failed ({collection}): {exc}")
        return False


async def record(collection: str, doc: dict):
    """Async, non-blocking insert."""
    if not mongo_enabled():
        return False
    try:
        return await asyncio.to_thread(_insert, collection, dict(doc))
    except Exception as exc:
        logger.warning(f"Mongo async insert failed ({collection}): {exc}")
        return False


async def log_event(user_id, kind: str, **payload):
    """Generic audit trail entry."""
    doc = {"user_id": int(user_id) if user_id else 0, "kind": kind}
    doc.update(payload)
    return await record("events", doc)


async def log_order(user_id, **payload):
    return await record("orders", {"user_id": int(user_id), **payload})


async def log_panel_order(user_id, **payload):
    return await record("panel_orders", {"user_id": int(user_id), **payload})


async def log_deposit(user_id, **payload):
    return await record("deposits", {"user_id": int(user_id), **payload})


async def log_redeem(user_id, **payload):
    return await record("redeems", {"user_id": int(user_id), **payload})


async def log_session(user_id, **payload):
    return await record("sessions", {"user_id": int(user_id), **payload})


def _fetch_history(user_id: int, limit: int):
    db = _get_db()
    if db is None:
        return None
    uid = int(user_id)
    out = {}
    for name in ("orders", "panel_orders", "deposits", "redeems", "sessions", "events"):
        try:
            out[name] = list(
                db[name].find({"user_id": uid}).sort("created_at", -1).limit(limit)
            )
        except Exception as exc:
            logger.warning(f"Mongo history read failed ({name}): {exc}")
            out[name] = []
    try:
        out["user"] = db.users.find_one({"user_id": uid})
    except Exception:
        out["user"] = None
    return out


async def get_user_history(user_id: int, limit: int = 100):
    """Full Mongo history for a user id (dict of lists), or None if disabled."""
    if not mongo_enabled():
        return None
    try:
        return await asyncio.to_thread(_fetch_history, int(user_id), int(limit))
    except Exception as exc:
        logger.warning(f"Mongo history failed: {exc}")
        return None


def _counts():
    db = _get_db()
    if db is None:
        return {}
    out = {}
    for name in COLLECTIONS:
        try:
            out[name] = db[name].estimated_document_count()
        except Exception:
            out[name] = 0
    return out


async def collection_counts():
    if not mongo_enabled():
        return {}
    try:
        return await asyncio.to_thread(_counts)
    except Exception:
        return {}


async def mirror_user(user_id, **fields):
    """Upsert the user document (balance, currency, language, ...)."""
    if not mongo_enabled():
        return False
    db = _get_db()
    if db is None:
        return False

    def _do():
        try:
            db.users.update_one(
                {"user_id": int(user_id)},
                {"$set": {**fields, "updated_at": _now()},
                 "$setOnInsert": {"user_id": int(user_id), "created_at": _now()}},
                upsert=True,
            )
            return True
        except Exception as exc:
            logger.warning(f"Mongo user mirror failed: {exc}")
            return False

    try:
        return await asyncio.to_thread(_do)
    except Exception:
        return False


def status_line() -> str:
    if not MONGO_URI:
        return "⚠️ MongoDB not configured (set MONGO_URI)"
    if not mongo_enabled():
        return "⚠️ MongoDB configured but pymongo missing or connection failed"
    return f"✅ MongoDB connected (db: {MONGO_DB})"
