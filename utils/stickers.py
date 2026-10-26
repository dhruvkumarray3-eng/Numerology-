"""Premium sticker / custom-emoji engine (country + app + purchase aware).

The owner can connect up to three Telegram packs:

    flags  ->  a custom-emoji pack of world flags   (t.me/addemoji/FlagsEmoji2024)
    apps   ->  a custom-emoji pack of app logos      (t.me/addemoji/ApplicationEmoji)
    misc   ->  a pack used on purchase / success     (t.me/addemoji/exppwebs_by_fStikBot)

Both *sticker packs* (``t.me/addstickers/...``) and *custom-emoji packs*
(``t.me/addemoji/...``) are supported.  Every document inside a pack carries an
"alt" value, so we can match:

    country name  ->  flag emoji   (utils.flags)  ->  document with that emoji
    app name      ->  app emoji    (ALL_APPS)     ->  document with that emoji

Custom-emoji documents are re-sent as real premium emoji using
``<tg-emoji emoji-id="...">`` so they render exactly like Telegram's own
premium emoji.  Plain sticker packs are re-sent as stickers.

Manual overrides always win: the owner can reply to any sticker/emoji with
``/mapsticker india`` and that exact document is pinned for that name.

Nothing here raises: if a pack is missing, private, or Telegram hiccups, the
helpers simply return ``None``/``False`` and the bot keeps working.
"""
import html
import json
import re
import time

from config import logger

# ---------------------------------------------------------------------------
# settings keys
# ---------------------------------------------------------------------------
K_PACK = "sticker_pack"                 # legacy single-pack key (-> flags)
K_PACK_FLAGS = "sticker_pack_flags"
K_PACK_APPS = "sticker_pack_apps"
K_PACK_MISC = "sticker_pack_misc"
K_MAP = "sticker_map"                   # JSON {name: {id, ah, fr, alt, kind}}
K_SEND = "sticker_send_mode"            # off | country | all

ROLES = ("flags", "apps", "misc")
ROLE_KEYS = {"flags": K_PACK_FLAGS, "apps": K_PACK_APPS, "misc": K_PACK_MISC}
ROLE_LABELS = {"flags": "Country flags", "apps": "App icons", "misc": "Purchase / success"}

# Sensible defaults so the three packs work out of the box.
_DEFAULTS = {
    "flags": "FlagsEmoji2024",
    "apps": "ApplicationEmoji",
    "misc": "exppwebs_by_fStikBot",
}
try:  # allow overriding through config / environment
    from config import STICKER_PACK_FLAGS, STICKER_PACK_APPS, STICKER_PACK_MISC
    if STICKER_PACK_FLAGS:
        _DEFAULTS["flags"] = STICKER_PACK_FLAGS
    if STICKER_PACK_APPS:
        _DEFAULTS["apps"] = STICKER_PACK_APPS
    if STICKER_PACK_MISC:
        _DEFAULTS["misc"] = STICKER_PACK_MISC
except Exception:  # pragma: no cover - config may not define them
    pass

_CACHE_TTL = 1800  # 30 min


def _blank_cache():
    return {"short": None, "by_emoji": {}, "by_text": {}, "docs": [], "at": 0.0,
            "is_emoji": False}


_CACHES = {role: _blank_cache() for role in ROLES}


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


def _norm_role(role):
    role = (role or "flags").strip().lower()
    return role if role in ROLES else "flags"


def get_pack_name(role="flags"):
    """Return the configured short-name for a role (falls back to defaults)."""
    role = _norm_role(role)
    val = (_get(ROLE_KEYS[role], "") or "").strip()
    if not val and role == "flags":
        val = (_get(K_PACK, "") or "").strip()
    return val or _DEFAULTS.get(role, "")


def set_pack_name(role_or_short, short=None):
    """set_pack_name("apps", "Foo") or legacy set_pack_name("Foo")."""
    if short is None:
        role, short = "flags", role_or_short
    role = _norm_role(role)
    ok = _set(ROLE_KEYS[role], short)
    _CACHES[role] = _blank_cache()
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
    """'https://t.me/addemoji/Foo' / 't.me/addstickers/Foo' / 'Foo' -> 'Foo'."""
    if not text:
        return ""
    t = str(text).strip()
    m = re.search(r"add(?:stickers|emoji)/([A-Za-z0-9_\-]+)", t)
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
    return s.split()[0] if s.split() else ""


# ---------------------------------------------------------------------------
# pack loading
# ---------------------------------------------------------------------------
def _doc_ref(doc, kind="sticker", alt=""):
    return {
        "id": int(doc.id),
        "ah": int(doc.access_hash),
        "fr": (doc.file_reference or b"").hex(),
        "alt": alt or "",
        "kind": kind,
    }


def _ref_to_input(ref):
    from telethon.tl.types import InputDocument
    return InputDocument(
        id=int(ref["id"]),
        access_hash=int(ref["ah"]),
        file_reference=bytes.fromhex(ref.get("fr") or ""),
    )


async def load_pack(bot=None, short_name=None, force=False, role="flags"):
    """Fetch + index a pack for a role.  Returns that role's cache (never raises)."""
    role = _norm_role(role)
    cache = _CACHES[role]
    name = (short_name or get_pack_name(role) or "").strip()
    if not name:
        return cache

    if (
        not force
        and cache["short"] == name
        and cache["at"]
        and (time.time() - cache["at"]) < _CACHE_TTL
    ):
        return cache

    if bot is None:
        try:
            from utils.helpers import get_bot_instance
            bot = get_bot_instance()
        except Exception:
            bot = None
    if bot is None:
        return cache

    try:
        from telethon.tl.functions.messages import GetStickerSetRequest
        from telethon.tl.types import (
            InputStickerSetShortName,
            DocumentAttributeSticker,
            DocumentAttributeCustomEmoji,
        )

        res = await bot(GetStickerSetRequest(
            stickerset=InputStickerSetShortName(short_name=name), hash=0
        ))
        docs = list(getattr(res, "documents", []) or [])
        by_emoji, by_text, refs = {}, {}, []
        is_emoji = False
        for doc in docs:
            alt = ""
            kind = "sticker"
            for attr in (getattr(doc, "attributes", []) or []):
                if isinstance(attr, DocumentAttributeCustomEmoji):
                    is_emoji = True
                    kind = "emoji"
                    alt = (getattr(attr, "alt", "") or "").strip()
                    break
                if isinstance(attr, DocumentAttributeSticker):
                    alt = (getattr(attr, "alt", "") or "").strip()
                    break
            ref = _doc_ref(doc, kind=kind, alt=alt)
            refs.append(ref)
            if not alt:
                continue
            emoji = _first_emoji(alt)
            if emoji and emoji not in by_emoji:
                by_emoji[emoji] = ref
            key = _norm(alt)
            if key and key not in by_text:
                by_text[key] = ref

        cache.update({
            "short": name,
            "by_emoji": by_emoji,
            "by_text": by_text,
            "docs": refs,
            "at": time.time(),
            "is_emoji": is_emoji,
        })
        logger.info(
            f"Sticker pack '{name}' [{role}] loaded: {len(refs)} docs, "
            f"{len(by_emoji)} emoji keys, emoji={is_emoji}"
        )
    except Exception as exc:
        logger.warning(f"Sticker pack '{name}' [{role}] could not be loaded: {exc}")
        cache.update({"short": name, "by_emoji": {}, "by_text": {}, "docs": [],
                      "at": time.time(), "is_emoji": False})
    return cache


def pack_stats(role="flags"):
    """Sync view of one role's cache for admin screens."""
    role = _norm_role(role)
    cache = _CACHES[role]
    return {
        "role": role,
        "label": ROLE_LABELS[role],
        "short": cache["short"] or get_pack_name(role) or "",
        "stickers": len(cache["docs"]),
        "emoji_keys": len(cache["by_emoji"]),
        "text_keys": len(cache["by_text"]),
        "age": int(time.time() - cache["at"]) if cache["at"] else None,
        "is_emoji": cache["is_emoji"],
        "mode": get_send_mode(),
        "manual": len(_load_map()),
    }


def all_stats():
    return {role: pack_stats(role) for role in ROLES}


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


def _resolve_in_cache(name, cache):
    key = _norm(name)
    if not key or not cache["docs"]:
        return None
    emoji = _emoji_for_name(name)
    if emoji:
        ref = cache["by_emoji"].get(emoji)
        if ref:
            return ref
    if key in cache["by_text"]:
        return cache["by_text"][key]
    # loose contains match (e.g. "united kingdom" vs "uk")
    for text_key, ref in cache["by_text"].items():
        if key and (key in text_key or text_key in key):
            return ref
    return None


def resolve(name, role=None, bot=None):
    """Name -> document ref (manual map first, then the given/auto role)."""
    key = _norm(name)
    if not key:
        return None

    manual = _load_map()
    for candidate in (key, key.replace(" ", "")):
        if candidate in manual:
            return manual[candidate]

    roles = [role] if role else list(ROLES)
    for r in roles:
        r = _norm_role(r)
        ref = _resolve_in_cache(name, _CACHES[r])
        if ref:
            return ref
    return None


# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------
async def _send_ref(bot, chat_id, ref, reply_to=None):
    """Send a document as premium emoji (custom-emoji pack) or as a sticker."""
    if ref.get("kind") == "emoji" and ref.get("alt"):
        tag = (f'<tg-emoji emoji-id="{int(ref["id"])}">'
               f'{html.escape(ref["alt"])}</tg-emoji>')
        await bot.send_message(chat_id, tag, parse_mode="html", reply_to=reply_to)
    else:
        await bot.send_file(chat_id, _ref_to_input(ref), reply_to=reply_to)


def _role_for_mode(mode_required, role):
    if role:
        return _norm_role(role)
    if mode_required in ("country", "flags"):
        return "flags"
    if mode_required in ("all", "app", "apps"):
        return "apps"
    return None


async def send_sticker(bot, chat_id, name, reply_to=None, mode_required=None,
                       role=None):
    """Send the matching premium emoji/sticker for `name`.  True when sent."""
    try:
        mode = get_send_mode()
        if mode == "off":
            return False
        if mode_required in ("all", "app", "apps") and mode != "all":
            return False

        chosen = _role_for_mode(mode_required, role)
        roles = [chosen] if chosen else ["flags", "apps"]
        for r in roles:
            r = _norm_role(r)
            if not get_pack_name(r):
                continue
            cache = _CACHES[r]
            if not cache["docs"]:
                cache = await load_pack(bot, role=r)
            if not cache["docs"]:
                continue
            ref = _resolve_in_cache(name, cache)
            if ref:
                await _send_ref(bot, chat_id, ref, reply_to=reply_to)
                return True
        return False
    except Exception as exc:
        logger.warning(f"send_sticker failed for '{name}': {exc}")
        return False


async def send_for_event(event, name, mode_required=None, reply_to=None,
                         role=None):
    """Convenience wrapper: send a premium emoji/sticker into `event`'s chat."""
    try:
        client = getattr(event, "client", None)
        chat_id = getattr(event, "chat_id", None)
        if client is None or chat_id is None:
            return False
        return await send_sticker(client, chat_id, name, reply_to=reply_to,
                                  mode_required=mode_required, role=role)
    except Exception as exc:
        logger.warning(f"send_for_event failed for '{name}': {exc}")
        return False


async def send_purchase(bot, chat_id, reply_to=None):
    """Send a celebration emoji from the `misc` pack (purchase / success)."""
    try:
        if get_send_mode() == "off":
            return False
        if not get_pack_name("misc"):
            return False
        cache = _CACHES["misc"]
        if not cache["docs"]:
            cache = await load_pack(bot, role="misc")
        if not cache["docs"]:
            return False
        preferred = ["\U0001F389", "\u2705", "\U0001F381", "\U0001F6CD",
                     "\U0001F4B8", "\U0001F680", "\u2B50", "\U0001F525"]
        ref = None
        for emoji in preferred:
            if emoji in cache["by_emoji"]:
                ref = cache["by_emoji"][emoji]
                break
        if ref is None:
            ref = cache["docs"][0]
        await _send_ref(bot, chat_id, ref, reply_to=reply_to)
        return True
    except Exception as exc:
        logger.warning(f"send_purchase failed: {exc}")
        return False


async def send_purchase_for_event(event, reply_to=None):
    try:
        client = getattr(event, "client", None)
        chat_id = getattr(event, "chat_id", None)
        if client is None or chat_id is None:
            return False
        return await send_purchase(client, chat_id, reply_to=reply_to)
    except Exception as exc:
        logger.warning(f"send_purchase_for_event failed: {exc}")
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
    """Build a ref from a received sticker/emoji document."""
    alt = ""
    kind = "sticker"
    try:
        from telethon.tl.types import (
            DocumentAttributeSticker, DocumentAttributeCustomEmoji,
        )
        for attr in (getattr(doc, "attributes", []) or []):
            if isinstance(attr, DocumentAttributeCustomEmoji):
                kind, alt = "emoji", (attr.alt or "").strip()
                break
            if isinstance(attr, DocumentAttributeSticker):
                alt = (attr.alt or "").strip()
                break
    except Exception:
        pass
    return _doc_ref(doc, kind=kind, alt=alt)
