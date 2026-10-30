"""Temp Mail client — Grabmail.io only, runtime-configurable.

Grabmail API (https://grabmail.io/api/v1):
    GET  /me                          key health, plan, rate limits
    GET  /domains                     public + premium pool
    GET  /mailbox?address=...         {address, alias, count, next, messages}
    GET  /message/{id}?mailbox=...    full body
    DEL  /message/{id}?mailbox=...    delete
    GET  /attachment/{id}?mailbox=... attachment

A mailbox is never created — it exists the moment mail arrives, and messages
are deleted 5 days after arrival.  Public domains (grabmail.io / mixozia.com /
linqmail.com) work keyless; the 97-domain premium pool needs a paid key.

Which key/base URL/domain is used comes from ``utils.runtime_config`` — i.e.
the admin panel first, then the environment.  That is what makes the API key
editable from the bot instead of a redeploy.

Public API (kept stable on purpose):
    get_domains(), create_email(), get_messages(), get_message(),
    extract_otp(), provider_name(), health(), test_connection()
"""
from __future__ import annotations

import asyncio
import html as _html
import random
import re
import time
from typing import Any, Dict, List, Optional

import aiohttp

from config import logger
from utils import runtime_config

_UA = "Numbott/1.0 (+temp-mail)"

# Domain list cache, keyed per key+base URL so rotating a key never shows the
# previous account's domains.
_DOMAIN_CACHE: Dict[str, Any] = {"key": "", "ts": 0.0, "domains": []}
_DOMAIN_TTL = 600


class TempMailError(Exception):
    """Raised for a user-facing Temp Mail failure."""


# ---------------------------------------------------------------------------
#  Settings
# ---------------------------------------------------------------------------
def settings() -> Dict[str, Any]:
    """Effective settings (panel -> env -> default)."""
    return runtime_config.tempmail_settings()


def enabled() -> bool:
    """True when the owner has Temp Mail switched ON in the admin panel."""
    return bool(settings().get("enabled", True))


def provider_name() -> str:
    return "grabmail"


def _require_key() -> str:
    """Grabmail keys are optional — public domains work keyless."""
    return (settings().get("api_key") or "").strip()


def _base() -> str:
    return _normalise_base(settings().get("base_url") or _GRABMAIL_CANON)


# The one and only GrabMail API root.  Every documented endpoint
# (/mailbox, /message/{id}, /domains, /me) hangs off this path.
_GRABMAIL_CANON = "https://grabmail.io/api/v1"


def _normalise_base(raw: str) -> str:
    """Return a canonical GrabMail API base URL.

    The admin panel lets the owner type any base URL, and a wrong host or
    path (``https://api.grabmail.io/v1``, a bare ``https://grabmail.io`` or a
    stray ``/messages`` suffix) used to 404 on *every* call.  Map the common
    mistakes onto the single real endpoint so a saved typo can never break
    Temp Mail again.
    """
    value = (raw or "").strip().rstrip("/")
    if not value:
        return _GRABMAIL_CANON
    low = value.lower()
    # Any grabmail.io host (api.grabmail.io, www.grabmail.io, grabmail.io,
    # .../v1/messages) collapses to the canonical API root.
    if "grabmail.io" in low:
        return _GRABMAIL_CANON
    # A self-hosted / custom domain: keep the host but guarantee /api/v1.
    if low.endswith("/api/v1"):
        return value
    if low.endswith("/api"):
        return value + "/v1"
    return value + "/api/v1"


def _headers() -> Dict[str, str]:
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    key = _require_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


# ---------------------------------------------------------------------------
#  HTTP
# ---------------------------------------------------------------------------
async def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 25,
) -> Dict[str, Any]:
    """JSON request with retry on 429/5xx. Error slugs are preserved."""
    url = f"{_base()}{path}"
    last_err: Optional[str] = None

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(headers=_headers()) as session:
                async with session.request(
                    method, url, params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        try:
                            wait = float(retry_after)
                        except (TypeError, ValueError):
                            wait = 1.5 * (attempt + 1)
                        last_err = "rate limit reached, please wait a moment"
                        await asyncio.sleep(min(wait, 10))
                        continue
                    if resp.status >= 500:
                        last_err = f"server error ({resp.status})"
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue

                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        raise TempMailError(
                            "Temp Mail service is temporarily unavailable. Please try again."
                        )
                    if not isinstance(data, dict):
                        raise TempMailError("Unexpected response from Temp Mail service.")

                    # Grabmail errors: {"error": slug, "message": "..."}
                    failed = (
                        resp.status >= 400
                        or data.get("status") is False
                        or bool(data.get("error"))
                    )
                    if failed:
                        slug = str(data.get("error") or "")
                        msg = (
                            data.get("message")
                            or (data.get("data") or {}).get("message")
                            or slug
                            or f"request failed ({resp.status})"
                        )
                        if slug == "unknown_domain":
                            msg = ("This domain is not available on your Grabmail plan. "
                                   "Premium domains need a paid key — pick grabmail.io, "
                                   "mixozia.com or linqmail.com instead.")
                        elif slug == "unauthorized":
                            msg = "Grabmail rejected the API key (401). Update it in the admin panel."
                        elif slug in ("quota_reached", "overage_cap", "overage_funds"):
                            msg = "Grabmail allowance for this month is used up."
                        elif slug == "address_taken":
                            msg = "That address is held by another Grabmail account. Try again."
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


# ---------------------------------------------------------------------------
#  Domains
# ---------------------------------------------------------------------------
async def get_domains(kind: str = "all", *, use_cache: bool = True) -> List[Dict[str, str]]:
    """Available domains as [{'domain': ..., 'type': ...}]."""
    cfg = settings()
    cache_key = f"{(cfg.get('api_key') or '')[:12]}:{cfg.get('base_url', '')}"

    now = time.time()
    if (
        use_cache
        and _DOMAIN_CACHE["domains"]
        and _DOMAIN_CACHE["key"] == cache_key
        and now - _DOMAIN_CACHE["ts"] < _DOMAIN_TTL
    ):
        return list(_DOMAIN_CACHE["domains"])

    cleaned: List[Dict[str, str]] = []
    data = await _request("GET", "/domains")
    for dom in data.get("public") or []:
        cleaned.append({"domain": str(dom), "type": "Free"})
    premium = data.get("premium") or {}
    if premium.get("unlocked"):
        for dom in premium.get("domains") or []:
            cleaned.append({"domain": str(dom), "type": "Premium"})

    if cleaned:
        _DOMAIN_CACHE.update({"key": cache_key, "domains": cleaned, "ts": now})
    return cleaned


# ---------------------------------------------------------------------------
#  Create / list / read
# ---------------------------------------------------------------------------
def _random_local(n: int = 9) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(random.choice(alphabet) for _ in range(n))


async def create_email(domain: Optional[str] = None) -> Dict[str, Any]:
    """Mint a fresh disposable inbox.

    Grabmail has no "create" call — an address exists as soon as mail arrives.
    We therefore mint a random local part, do one read so the alias and the
    premium hold are established, and return a stable payload.
    """
    cfg = settings()
    domain = (domain or cfg.get("domain") or "").strip().lstrip("@")

    if not domain:
        domains = await get_domains()
        domain = domains[0]["domain"] if domains else "grabmail.io"
    address = f"{_random_local()}@{domain}"
    alias = None
    try:
        data = await _request("GET", "/mailbox", params={"address": address, "limit": 1})
        alias = data.get("alias")
    except TempMailError as exc:
        # A 404/429 must not stop the user: the address still receives mail.
        logger.debug(f"grabmail pre-read skipped: {exc}")
    return {
        "email": address,
        "id": address,
        "alias": alias,
        "domain": domain,
        "provider": "grabmail",
        "expire_at": "5 days (auto-deleted)",
    }


async def get_alias(email: str) -> str:
    """Return the forwarding alias for ``email`` ('' when unavailable).

    Grabmail gives every mailbox a second address on a different domain that
    delivers to the same inbox.  Handy when a signup form rejects the public
    domain but accepts the alias domain.
    """
    if not email:
        return ""
    try:
        data = await _request(
            "GET", "/mailbox", params={"address": email, "limit": 1}
        )
        return str(data.get("alias") or "")
    except Exception as exc:  # noqa: BLE001 - alias is best-effort
        logger.debug(f"grabmail alias lookup failed: {exc}")
        return ""


def _normalise_message(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Grabmail's field names into one stable shape."""
    if not isinstance(raw, dict):
        return {}
    body = (
        raw.get("text")
        or raw.get("body")
        or raw.get("html")
        or raw.get("body_html")
        or raw.get("content")
        or raw.get("message")
        or ""
    )
    return {
        "id": raw.get("id") or raw.get("message_id") or raw.get("uid"),
        "from": raw.get("from") or raw.get("from_email") or raw.get("sender") or "Unknown sender",
        "subject": raw.get("subject") or "(no subject)",
        "date": raw.get("date") or raw.get("created_at") or raw.get("received_at") or "",
        "body": body,
        "seen": bool(raw.get("seen")),
        "attachments": raw.get("attachments") or 0,
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
    """Inbox messages for ``email``, newest first."""
    if not email:
        return []
    data = await _request("GET", "/mailbox", params={"address": email, "limit": 50})
    raw = data.get("messages") or []

    out: List[Dict[str, Any]] = []
    for item in raw:
        norm = _normalise_message(item)
        if norm:
            out.append(norm)

    def _sort_key(m):
        return str(m.get("date") or m.get("id") or "")

    out.sort(key=_sort_key, reverse=True)
    return out


async def get_message(email: str, message_id: Any) -> Dict[str, Any]:
    """Fetch one message with its full body."""
    try:
        data = await _request("GET", f"/message/{message_id}", params={"mailbox": email})
        return _normalise_message(data)
    except TempMailError as exc:
        logger.debug(f"grabmail message fetch failed: {exc}")
        return {"id": message_id, "from": "", "subject": "", "date": "",
                "body": "", "raw": {}}


async def delete_message(email: str, message_id: Any) -> bool:
    """Delete a message at once."""
    try:
        data = await _request("DELETE", f"/message/{message_id}", params={"mailbox": email})
        return bool(data.get("deleted"))
    except TempMailError:
        return False


# ---------------------------------------------------------------------------
#  Health / test
# ---------------------------------------------------------------------------
async def health() -> Dict[str, Any]:
    """Non-raising status snapshot for the admin panel."""
    cfg = settings()
    info: Dict[str, Any] = {
        "provider": "grabmail",
        "enabled": cfg.get("enabled", True),
        "base_url": cfg.get("base_url"),
        "website_url": cfg.get("website_url"),
        "domain": cfg.get("domain"),
        "source": cfg.get("source"),
        "key": runtime_config.mask(cfg.get("api_key", "")),
        "ok": False,
    }
    try:
        if (cfg.get("api_key") or "").strip():
            me = await _request("GET", "/me")
            usage = me.get("usage") or {}
            info.update({
                "ok": True,
                "plan": me.get("plan"),
                "premium": me.get("premium"),
                "left": usage.get("left"),
                "quota": usage.get("quota"),
                "limits": me.get("limits"),
            })
        else:
            # No key: /me would answer 401, but the public domains are
            # keyless and fully usable.  Probe /domains instead so the
            # panel shows "Working" for the normal no-key setup.
            data = await _request("GET", "/domains")
            public = data.get("public") or []
            info.update({
                "ok": bool(public),
                "plan": "free (no key)",
                "premium": False,
                "domains": len(public),
            })
    except Exception as exc:
        info["error"] = str(exc)
    return info


async def test_connection() -> Dict[str, Any]:
    """Create a throwaway inbox to prove the key/base URL really work."""
    data = await create_email()
    return {"ok": True, "email": data.get("email"), "provider": data.get("provider"),
            "expire_at": data.get("expire_at")}


# ---------------------------------------------------------------------------
#  OTP extraction
# ---------------------------------------------------------------------------
_CODE_WORDS = ("code", "otp", "pin", "password", "passcode", "verification",
               "verify", "confirm", "token", "login", "signin", "auth")


def extract_otp(text: str, length: Optional[int] = None) -> Optional[str]:
    """Best OTP candidate from a mail body.

    Scores candidates instead of returning the first number, because the first
    number in a real mail is usually a year, a price or an expiry ("10
    minutes") — the classic cause of "wrong code" complaints.
    """
    if not text:
        return None
    if "<" in text:
        text = _strip_html(text)
    text = re.sub(r"(?<=\d)[ \u00a0](?=\d)", "", text)

    best: Optional[str] = None
    best_score = -10**9
    for m in re.finditer(r"\b(\d{4,8})\b", text):
        value = m.group(1)
        if length and len(value) != length:
            continue
        start = max(0, m.start() - 70)
        window = text[start:m.end() + 70].lower()
        score = 0
        if any(w in window for w in _CODE_WORDS):
            score += 40
        if len(value) == 6:
            score += 20
        elif len(value) == 5:
            score += 12
        elif len(value) == 4:
            score += 8
        if re.search(r"\b(?:19|20)\d{2}\b", window):
            score -= 15
        if re.search(r"\d+\s?(?:min|mins|minute|minutes|sec|seconds|hour|hours|day|days)", window):
            score -= 15
        if len(set(value)) == 1:
            score -= 40
        if score > best_score:
            best_score, best = score, value
    return best
