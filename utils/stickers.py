"""Premium sticker-pack engine (country + app aware).

The owner drops a *sticker pack link* (``https://t.me/addstickers/MyPack``) and
the bot learns the whole pack.  Every sticker inside a Telegram pack carries an
"alt" emoji, so we can match:

    country name  ->  flag emoji   (utils.flags)  ->  sticker with that emoji
    app name      ->  app emoji    (ALL_APPS)     ->  sticker with that emoji

Manual overrides always win: the owner can reply to any sticker with
``/mapsticker india`` and that exact sticker is pinned for that name.

Nothing here raises: if the pack is missing, private, or Telegram hiccups, the
helpers simply return ``None`` and the bot keeps working.
"""
import json
import re
import time

from config import logger

K_PACK = "sticker_pack"          # short_name of the active pack
K_MAP = "sticker_map"            # JSON {name: {id, ah, fr}}
K_SEND = "sticker_send_mode"     # off | country | all

_CACHE = {"short": None, "by_emoji": {}, "by_text": {}, "docs": [], "at": 0.0}
_CACHE_TTL = 1800  # 30 min


# ---------------------------------------------------------------------------
# settings helpers
# ---------------------------------------------------------------------------
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
        logger.warning(f"sticker setting read failed ({key}): {exc}")
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
        logger.warning(f"sticker setting write failed ({key}): {exc}")
        return False


def get_pack_name():
    return (_get(K_PACK, "") or "").strip()


def set_pack_name(short_name):
    ok = _set(K_PACK, short_name)
    _CACHE.update({"short": None, "by_emoji": {}, "by_text": {}, "docs": [], "at": 0.0})
    return ok


def get_send_mode():
    mode = (_get(K_SEND, "country") or "country").strip().lower()
    return mode if mode in ("off", "country", "all") else "country"


def set_send_mode(mode):
    mode = (mode or "").strip().lower()
    if mode not in ("off", "country", "all"):
        return False
    return _set(K_SEND, mode)


def _load_map():
    raw = _get(K_MAP, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_map(mapping):
    try:
        return _set(K_MAP, json.dumps(mapping, ensure_ascii=False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# link parsing
# ---------------------------------------------------------------------------
def parse_pack_link(text):
    """'https://t.me/addstickers/Foo' / 't.me/addstickers/Foo' / 'Foo' -> 'Foo'."""
    if not text:
        return ""
    t = str(text).strip()
    m = re.search(r"addstickers/([A-Za-z0-9_\-]+)", t)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|\s)([A-Za-z0-9_\-]{3,64})(?:\s|$)", t)
    if m and "/" not in t:
        return m.group(1)
    return ""


def _norm(name):
    """Lower-case, strip emoji/punctuation so 'India 🇮🇳' == 'india'."""
    s = str(name or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _first_emoji(text):
    """Return the first emoji-ish cluster of a string (sticker alt is usually one)."""
    if not text:
        return ""
    s = str(text).strip()
    # strip variation selectors / zero-width joiners noise at the edges
    return s.split()[0] if s.split() else ""


# ---------------------------------------------------------------------------
# pack loading
# ---------------------------------------------------------------------------
def _doc_ref(doc):
    return {
        "id": int(doc.id),
        "ah": int(doc.access_hash),
        "fr": (doc.file_reference or b"").hex(),
    }


def _ref_to_input(ref):
    from telethon.tl.types import InputDocument
    return InputDocument(
        id=int(ref["id"]),
        access_hash=int(ref["ah"]),
        file_reference=bytes.fromhex(ref.get("fr") or ""),
    )


async def load_pack(bot=None, short_name=None, force=False):
    """Fetch + index the sticker pack.  Returns the cache dict (never raises)."""
    name = (short_name or get_pack_name() or "").strip()
    if not name:
        return _CACHE

    if (
        not force
        and _CACHE["short"] == name
        and _CACHE["docs"]
        and (time.time() - _CACHE["at"]) < _CACHE_TTL
    ):
        return _CACHE

    if bot is None:
        try:
            from utils.helpers import get_bot_instance
            bot = get_bot_instance()
        except Exception:
            bot = None
    if bot is None:
        return _CACHE

    try:
        from telethon.tl.functions.messages import GetStickerSetRequest
        from telethon.tl.types import InputStickerSetShortName, DocumentAttributeSticker

        res = await bot(GetStickerSetRequest(
            stickerset=InputStickerSetShortName(short_name=name), hash=0
        ))
        docs = list(getattr(res, "documents", []) or [])
        by_emoji, by_text, refs = {}, {}, []
        for doc in docs:
            ref = _doc_ref(doc)
            refs.append(ref)
            alt = ""
            for attr in (getattr(doc, "attributes", []) or []):
                if isinstance(attr, DocumentAttributeSticker):
                    alt = (attr.alt or "").strip()
                    break
            if not alt:
                continue
            emoji = _first_emoji(alt)
            if emoji and emoji not in by_emoji:
                by_emoji[emoji] = ref
            key = _norm(alt)
            if key and key not in by_text:
                by_text[key] = ref

        _CACHE.update({
            "short": name,
            "by_emoji": by_emoji,
            "by_text": by_text,
            "docs": refs,
            "at": time.time(),
        })
        logger.info(f"Sticker pack '{name}' loaded: {len(refs)} stickers, "
                    f"{len(by_emoji)} emoji keys")
    except Exception as exc:
        logger.warning(f"Sticker pack '{name}' could not be loaded: {exc}")
        _CACHE.update({"short": name, "by_emoji": {}, "by_text": {}, "docs": [], "at": time.time()})
    return _CACHE


def pack_stats():
    """Sync view of the cache for admin screens."""
    return {
        "short": _CACHE["short"] or get_pack_name() or "",
        "stickers": len(_CACHE["docs"]),
        "emoji_keys": len(_CACHE["by_emoji"]),
        "text_keys": len(_CACHE["by_text"]),
        "age": int(time.time() - _CACHE["at"]) if _CACHE["at"] else None,
        "mode": get_send_mode(),
        "manual": len(_load_map()),
    }


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def _emoji_for_name(name):
    """Country/app name -> emoji, using the flag resolver + app icon table."""
    key = _norm(name)
    if not key:
        return ""
    # 1. country flag
    try:
        from utils.flags import flag_for
        flag = flag_for(name)
        if flag and flag != "\U0001F30D":
            return flag
    except Exception:
        pass
    # 2. app icon from ALL_APPS
    try:
        from plugins.product_panels import ALL_APPS
        for app_key, label in ALL_APPS:
            if key in (_norm(app_key), _norm(label)) or key in _norm(label):
                parts = label.strip().split()
                if parts and len(parts[0]) <= 3:
                    return parts[0]
    except Exception:
        pass
    return ""


def resolve(name, bot=None):
    """Name -> sticker ref (manual map first, then emoji, then text)."""
    key = _norm(name)
    if not key:
        return None

    manual = _load_map()
    for candidate in (key, key.replace(" ", "")):
        if candidate in manual:
            return manual[candidate]

    cache = _CACHE if _CACHE["docs"] else None
    if cache is None:
        return None

    emoji = _emoji_for_name(name)
    if emoji:
        ref = _CACHE["by_emoji"].get(emoji)
        if ref:
            return ref

    if key in _CACHE["by_text"]:
        return _CACHE["by_text"][key]

    # loose contains match (e.g. "united kingdom" vs "uk")
    for text_key, ref in _CACHE["by_text"].items():
        if key and (key in text_key or text_key in key):
            return ref
    return None


async def send_sticker(bot, chat_id, name, reply_to=None, mode_required=None):
    """Send the matching sticker for `name`.  Returns True when one was sent."""
    try:
        mode = get_send_mode()
        if mode == "off":
            return False
        if mode_required and mode != mode_required and mode != "all":
            return False
        if not get_pack_name():
            return False
        if not _CACHE["docs"]:
            await load_pack(bot)
        ref = resolve(name, bot)
        if not ref:
            return False
        await bot.send_file(chat_id, _ref_to_input(ref), reply_to=reply_to)
        return True
    except Exception as exc:
        logger.warning(f"send_sticker failed for '{name}': {exc}")
        return False


async def send_for_event(event, name, mode_required=None, reply_to=None):
    """Convenience wrapper: send a sticker into the chat behind `event`."""
    try:
        client = getattr(event, "client", None)
        chat_id = getattr(event, "chat_id", None)
        if client is None or chat_id is None:
            return False
        return await send_sticker(client, chat_id, name, reply_to=reply_to,
                                  mode_required=mode_required)
    except Exception as exc:
        logger.warning(f"send_for_event failed for '{name}': {exc}")
        return False


# ---------------------------------------------------------------------------
# manual mapping
# ---------------------------------------------------------------------------
def map_name(name, ref):
    mapping = _load_map()
    mapping[_norm(name)] = ref
    return _save_map(mapping)


def unmap_name(name):
    mapping = _load_map()
    removed = mapping.pop(_norm(name), None) is not None
    if removed:
        _save_map(mapping)
    return removed


def list_map(limit=60):
    return list(_load_map().items())[:limit]


def ref_from_document(doc):
    return _doc_ref(doc)
