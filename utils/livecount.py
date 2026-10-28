"""
Live auto-updating message engine.

Telegram messages cannot tick on their own, so this module keeps a registry of
"live" messages and runs a single background worker that re-renders and edits
each one on a fixed interval (default 5s).  Only messages whose rendered text
actually changed are edited, which keeps us well inside Telegram's rate limits.

Used by:
  * Temp Mail inbox  -> "Time Remaining: 49:12" ticks down every second-ish
  * Account / OTP order card -> "Session expires in 09:41"
  * All-Apps OTP panels -> same countdown

Usage:
    from utils.livecount import register_live, unregister_live

    async def _render():
        # must return (text, buttons, finished)
        return text, buttons, expired

    register_live(f"tm:{uid}:{email}", bot, chat_id, msg_id, _render, interval=5)

The worker automatically drops the entry when `finished` is True or when the
edit fails (message deleted / too old / bot removed).
"""
import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

RenderFn = Callable[[], Awaitable[Tuple[str, Any, bool]]]

_REGISTRY: Dict[str, dict] = {}
_WORKER: Optional[asyncio.Task] = None
_TICK = 1.0          # how often the worker wakes up
_MIN_EDIT_GAP = 4.0  # never edit the same message faster than this


def _ensure_worker() -> None:
    global _WORKER
    if _WORKER is None or _WORKER.done():
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                _WORKER = loop.create_task(_worker())
        except RuntimeError:
            pass


def register_live(
    key: str,
    bot,
    chat_id: int,
    msg_id: int,
    render: RenderFn,
    interval: float = 5.0,
    ttl: Optional[float] = None,
) -> None:
    """Start (or restart) live ticking for one message."""
    now = time.time()
    _REGISTRY[key] = {
        "bot": bot,
        "chat_id": chat_id,
        "msg_id": msg_id,
        "render": render,
        "interval": max(_MIN_EDIT_GAP, float(interval)),
        "next": now + 1.0,
        "last": None,
        "deadline": (now + ttl) if ttl else None,
        "failures": 0,
    }
    _ensure_worker()


def unregister_live(key: str) -> None:
    _REGISTRY.pop(key, None)


def unregister_prefix(prefix: str) -> None:
    for k in [k for k in _REGISTRY if k.startswith(prefix)]:
        _REGISTRY.pop(k, None)


def is_live(key: str) -> bool:
    return key in _REGISTRY


async def _worker() -> None:
    from telethon.errors import MessageNotModifiedError

    while True:
        try:
            await asyncio.sleep(_TICK)
        except asyncio.CancelledError:
            return

        now = time.time()
        for key in list(_REGISTRY.keys()):
            entry = _REGISTRY.get(key)
            if entry is None:
                continue
            if now < entry["next"]:
                continue
            entry["next"] = now + entry["interval"]

            if entry["deadline"] and now > entry["deadline"]:
                _REGISTRY.pop(key, None)
                continue

            try:
                text, buttons, finished = await entry["render"]()
            except Exception as exc:  # render bug -> stop ticking, don't spam logs
                logger.debug("livecount render failed for %s: %s", key, exc)
                entry["failures"] += 1
                if entry["failures"] >= 3:
                    _REGISTRY.pop(key, None)
                continue

            # The render can await a network request. If a cancel action removed
            # this job during that await, do not let the stale result edit the
            # message after the cancellation handler has replaced its contents.
            if _REGISTRY.get(key) is not entry:
                continue

            entry["failures"] = 0

            if text != entry["last"]:
                try:
                    await entry["bot"].edit_message(
                        entry["chat_id"], entry["msg_id"], text, buttons=buttons
                    )
                    entry["last"] = text
                except MessageNotModifiedError:
                    entry["last"] = text
                except Exception as exc:
                    logger.debug("livecount edit failed for %s: %s", key, exc)
                    _REGISTRY.pop(key, None)
                    continue

            if finished:
                _REGISTRY.pop(key, None)
