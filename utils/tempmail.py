"""MTempMail API client (https://mtempmail.com/api).

Powers the free "Temp Mail" section of the bot: users can spin up a
disposable inbox, read incoming verification emails / OTPs, and refresh.

API reference (verified live against the public key):

    GET  /domains/{apiKey}/{type}          -> {"status": true, "data": {"domains": [...]}}
    POST /emails/{apiKey}                  -> {"status": true, "data": {"email": ..., "id": ..., ...}}
    GET  /messages/{apiKey}/{email}        -> {"status": true, "mailbox": ..., "messages": [...]}

Message objects in the list normally carry ``id``, ``from_email``,
``subject``, ``created_at`` and often the rendered ``body``/``html``.
When the body is missing we try the per-message endpoint and finally fall
back to the public web view (``/view/{id}``) so the user always sees the
mail content.

The public key is rate-limited (~120 req/min per IP).  All calls are
wrapped in a small retry/back-off so a temporary 429 never breaks the UI.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
import time
from typing import Any, Dict, List, Optional

import aiohttp

from config import TEMPMAIL_API_KEY, TEMPMAIL_BASE_URL, logger

# Cache the domain list for a while -- it changes rarely.
_DOMAIN_CACHE: Dict[str, Any] = {"ts": 0.0, "domains": []}
_DOMAIN_TTL = 600  # seconds

_UA = "Numbott/1.0 (+https://mtempmail.com)"


class TempMailError(Exception):
    """Raised for a user-facing Temp Mail failure."""


def _key() -> str:
    key = (TEMPMAIL_API_KEY or "").strip()
    if not key:
        raise TempMailError("Temp Mail API key is not configured.")
    return key


def _base() -> str:
    return (TEMPMAIL_BASE_URL or "https://mtempmail.com/api").rstrip("/")


async def _request(method: str, path: str, *, timeout: int = 25) -> Dict[str, Any]:
    """Perform a JSON request with one retry on 429/5xx."""
    url = f"{_base()}{path}"
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    last_err: Optional[str] = None
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.request(method, url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    text = await resp.text()
                    if resp.status == 429:
                        last_err = "rate limit reached, please wait a moment"
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    if resp.status >= 500:
                        last_err = f"server error ({resp.status})"
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        # Some errors are plain HTML; surface a clean message.
                        raise TempMailError(
                            "Temp Mail service is temporarily unavailable. Please try again."
                        )
                    if not isinstance(data, dict):
                        raise TempMailError("Unexpected response from Temp Mail service.")
                    if resp.status >= 400 or data.get("status") is False:
                        msg = (
                            data.get("message")
                            or (data.get("data") or {}).get("message")
                            or f"request failed ({resp.status})"
                        )
                        raise TempMailError(str(msg))
                    return data
        except TempMailError:
            raise
        except asyncio.TimeoutError:
            last_err = "request timed out"
        except aiohttp.ClientError as exc:
            last_err = f"network error: {exc}"
        await asyncio.sleep(0.8 * (attempt + 1))
    raise TempMailError(last_err or "Temp Mail request failed.")


# --------------------------------------------------------------------------- #
#  Public helpers
# --------------------------------------------------------------------------- #
async def get_domains(kind: str = "all", *, use_cache: bool = True) -> List[Dict[str, str]]:
    """Return the list of available domains: [{'domain': ..., 'type': ...}]."""
    now = time.time()
    if use_cache and _DOMAIN_CACHE["domains"] and now - _DOMAIN_CACHE["ts"] < _DOMAIN_TTL:
        return list(_DOMAIN_CACHE["domains"])
    data = await _request("GET", f"/domains/{_key()}/{kind}")
    domains = ((data.get("data") or {}).get("domains")) or []
    cleaned = [
        {"domain": str(d.get("domain", "")).strip(), "type": str(d.get("type", "Free")).strip()}
        for d in domains
        if isinstance(d, dict) and d.get("domain")
    ]
    if cleaned:
        _DOMAIN_CACHE["domains"] = cleaned
        _DOMAIN_CACHE["ts"] = now
    return cleaned


async def create_email(domain: Optional[str] = None) -> Dict[str, Any]:
    """Create a fresh disposable inbox.

    ``domain`` is optional; the API picks a free domain automatically when
    omitted.  Returns the full ``data`` object (email, id, expire_at, ...).
    """
    path = f"/emails/{_key()}"
    if domain:
        path += f"?domain={domain}"
    data = await _request("POST", path)
    payload = data.get("data") or {}
    if not payload.get("email"):
        raise TempMailError("Could not create a temporary email. Please try again.")
    return payload


def _normalise_message(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map the various field names the API may use into one stable shape."""
    if not isinstance(raw, dict):
        return {}
    body = (
        raw.get("body")
        or raw.get("html")
        or raw.get("body_html")
        or raw.get("content")
        or raw.get("text")
        or raw.get("message")
        or ""
    )
    return {
        "id": raw.get("id") or raw.get("message_id") or raw.get("uid"),
        "from": raw.get("from_email") or raw.get("from") or raw.get("sender") or "Unknown sender",
        "subject": raw.get("subject") or "(no subject)",
        "date": raw.get("created_at") or raw.get("date") or raw.get("received_at") or "",
        "body": body,
        "raw": raw,
    }


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


async def get_messages(email: str) -> List[Dict[str, Any]]:
    """Return the inbox messages for ``email`` (newest first)."""
    if not email:
        return []
    data = await _request("GET", f"/messages/{_key()}/{email}")
    raw = data.get("messages") or data.get("data") or []
    if isinstance(raw, dict):
        raw = raw.get("messages") or []
    out: List[Dict[str, Any]] = []
    for item in raw:
        norm = _normalise_message(item)
        if norm:
            out.append(norm)
    # Newest first when a timestamp/id is available.
    def _sort_key(m):
        return str(m.get("date") or m.get("id") or "")
    out.sort(key=_sort_key, reverse=True)
    return out


async def get_message(email: str, message_id: Any) -> Dict[str, Any]:
    """Fetch one message with its full body, trying several fallbacks."""
    # 1) Try documented-style per-message endpoints.
    candidates = [
        f"/messages/{_key()}/{email}/{message_id}",
        f"/message/{_key()}/{email}/{message_id}",
        f"/messages/{_key()}/{message_id}",
        f"/message/{_key()}/{message_id}",
    ]
    for path in candidates:
        try:
            data = await _request("GET", path)
        except TempMailError:
            continue
        payload = data.get("data") or data.get("message") or data
        norm = _normalise_message(payload if isinstance(payload, dict) else {})
        if norm.get("body"):
            return norm

    # 2) Fall back to the public web view and strip the HTML.
    if message_id:
        try:
            url = f"https://mtempmail.com/view/{message_id}"
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                    if resp.status == 200:
                        page = await resp.text()
                        text = _strip_html(page)
                        if text:
                            return {
                                "id": message_id,
                                "from": "",
                                "subject": "",
                                "date": "",
                                "body": text,
                                "raw": {},
                            }
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug(f"tempmail web fallback failed: {exc}")

    return {"id": message_id, "from": "", "subject": "", "date": "", "body": "", "raw": {}}


def extract_otp(text: str) -> Optional[str]:
    """Best-effort OTP / verification-code extraction from a mail body."""
    if not text:
        return None
    patterns = [
        r"(?i)\b(?:code|otp|pin|password)\D{0,15}(\d{4,8})\b",
        r"\b(\d{6})\b",
        r"\b(\d{4,8})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None
