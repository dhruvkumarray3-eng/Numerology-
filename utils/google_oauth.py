"""Google Login (OAuth 2.0) for Gmail IMAP.

Why this exists
---------------
Google stopped accepting a normal Gmail password for IMAP years ago, and it
also rejects App Passwords for many accounts (Workspace tenants, Advanced
Protection, or accounts where 2-Step Verification is enforced differently).
The *only* login method Google guarantees is OAuth 2.0, which IMAP speaks as
``XOAUTH2``.

This module implements the full "Sign in with Google" flow inside the bot:

1. ``auth_url()`` builds a consent link.  The owner opens it, signs in with
   their **normal Google password** on Google's own page (the bot never sees
   it), and Google redirects to ``http://localhost/?code=...``.
2. The browser cannot reach localhost, so the owner simply copies the address
   bar (or just the ``code=`` value) and pastes it back into the bot.
3. ``exchange_code()`` trades that one-time code for a long-lived
   ``refresh_token`` which is stored in the settings table.
4. ``imap_login()`` mints short-lived access tokens from the refresh token and
   authenticates IMAP with XOAUTH2.

Everything is plain ``urllib`` - no extra dependency, works on Python 3.11+.
"""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from config import logger
from database import cur, db

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

# Full mailbox access.  ``https://mail.google.com/`` is the scope Google
# documents for IMAP/SMTP XOAUTH2.
SCOPE = "https://mail.google.com/"

# Desktop ("installed app") clients are allowed to use a loopback redirect with
# any port; http://localhost is the least surprising one to show a user.
REDIRECT_URI = "http://localhost"

KEY_CLIENT_ID = "google_client_id"
KEY_CLIENT_SECRET = "google_client_secret"
KEY_REFRESH = "google_refresh_token"
KEY_EMAIL = "google_account_email"

# ---------------------------------------------------------------------------
# Built-in OAuth client (project ``numerology-oauth``).
#
# These are the credentials of the bot owner's own Google Cloud project, baked
# in so that a fresh deployment works immediately: no wizard, no copy-paste.
# They are only a *fallback* -- anything stored in the settings table or passed
# through the panel environment wins, so the owner can still swap the client
# from the UI or from Pterodactyl variables at any time.
# ---------------------------------------------------------------------------
DEFAULT_CLIENT_ID = (
    "1001300537784-8lpg0tk4satrtts2k83gdcu30uuvdtp0"
    ".apps.googleusercontent.com"
)
DEFAULT_CLIENT_SECRET = "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"

# Access tokens live ~1 hour; refresh a little early to avoid races.
_TOKEN_CACHE = {"token": "", "expires_at": 0.0, "email": ""}
_EXPIRY_SKEW = 120


# ---------------------------------------------------------------------------
# settings helpers
# ---------------------------------------------------------------------------
def _get(key, default=""):
    try:
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row and row[0] is not None and str(row[0]).strip():
            return str(row[0]).strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("google_oauth setting read failed (%s): %s", key, exc)
    return default


def _set(key, value):
    try:
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, "" if value is None else str(value)),
        )
        db.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("google_oauth setting write failed (%s): %s", key, exc)
        return False


def client_credentials():
    """Return ``(client_id, client_secret)`` as configured, or ``("", "")``.

    The panel wizard stores the pair in the settings table, but the same values
    can also be supplied through the hosting panel's environment variables
    (``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET``).  That way the owner can
    set them once in Pterodactyl and never touch the bot UI.
    """
    client_id = (
        _get(KEY_CLIENT_ID)
        or os.getenv("GOOGLE_CLIENT_ID", "").strip()
        or DEFAULT_CLIENT_ID
    )
    secret = (
        _get(KEY_CLIENT_SECRET)
        or os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        or DEFAULT_CLIENT_SECRET
    )
    return client_id, secret


def save_client_credentials(client_id, client_secret):
    """Persist the OAuth client pair created in Google Cloud Console."""
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    ok = _set(KEY_CLIENT_ID, client_id)
    ok = _set(KEY_CLIENT_SECRET, client_secret) and ok
    return ok


def has_client():
    cid, secret = client_credentials()
    return bool(cid and secret)


def has_refresh_token():
    return bool(_get(KEY_REFRESH))


def connected_email():
    return _get(KEY_EMAIL)


def is_connected():
    return has_client() and has_refresh_token()


def disconnect():
    """Forget the stored Google login (client credentials are kept)."""
    _set(KEY_REFRESH, "")
    _set(KEY_EMAIL, "")
    _TOKEN_CACHE.update({"token": "", "expires_at": 0.0, "email": ""})


# ---------------------------------------------------------------------------
# step 1 - consent URL
# ---------------------------------------------------------------------------
def auth_url(state="numerology"):
    """Build the Google consent link the owner has to open."""
    client_id, _secret = client_credentials()
    if not client_id:
        return ""
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # required to receive a refresh_token
        "prompt": "consent",        # force a refresh_token even on re-auth
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


_CODE_RE = re.compile(r"[?&]code=([A-Za-z0-9._\-/%]+)")
_RAW_CODE_RE = re.compile(r"^[A-Za-z0-9._\-/]{20,}$")


def extract_code(text):
    """Pull the ``code`` out of whatever the owner pasted.

    Accepts the whole redirect URL (``http://localhost/?code=4/0A...``), a
    ``code=...`` fragment, or the bare code.  Returns ``""`` when nothing
    usable is found.
    """
    raw = "" if text is None else str(text).strip()
    if not raw:
        return ""
    raw = raw.replace("\u200b", "").replace("\u00a0", " ")

    match = _CODE_RE.search(raw)
    if match:
        return urllib.parse.unquote(match.group(1)).strip()

    # "code=4/0AX4XfWh..." without the leading ? or &
    match = re.search(r"code=([A-Za-z0-9._\-/%]+)", raw)
    if match:
        return urllib.parse.unquote(match.group(1)).strip()

    # Bare code, possibly wrapped in quotes.
    candidate = raw.strip(" \t\r\n\"'`<>")
    if _RAW_CODE_RE.match(candidate):
        return candidate
    return ""


# ---------------------------------------------------------------------------
# step 2 - token exchange
# ---------------------------------------------------------------------------
def _post_form(url, data, timeout=20):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _friendly_error(exc):
    """Turn a Google token-endpoint failure into something actionable."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            payload = json.loads(exc.read().decode("utf-8", "ignore"))
        except Exception:
            payload = {}
        code = payload.get("error", "")
        desc = payload.get("error_description", "")
        if code == "invalid_grant":
            return ("Google rejected the code/token (invalid_grant).\n"
                    "The code was already used, expired, or the login was revoked.\n"
                    "Start the Google Login again and paste the FRESH code.")
        if code == "redirect_uri_mismatch":
            return ("redirect_uri_mismatch: in Google Cloud Console the OAuth client "
                    "must be of type 'Desktop app' (installed application).")
        if code == "invalid_client":
            return ("invalid_client: the Client ID / Client Secret do not match. "
                    "Re-copy them from Google Cloud Console.")
        if code == "unauthorized_client":
            return ("unauthorized_client: this OAuth client cannot request the "
                    "Gmail scope. Create a 'Desktop app' client.")
        return f"{code or 'HTTP error'}: {desc or exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"Network error reaching Google: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def exchange_code(code, timeout=20):
    """Trade a one-time authorisation code for a refresh token.

    Returns ``(True, {"email": ..., "refresh_token": ...})`` or
    ``(False, "reason")``.  Never raises.
    """
    client_id, client_secret = client_credentials()
    if not client_id or not client_secret:
        return False, ("Google OAuth client is not configured yet. "
                       "Set the Client ID and Client Secret first.")
    code = extract_code(code)
    if not code:
        return False, ("Could not find a code in that message. Paste the whole "
                       "link you were redirected to (it contains code=...).")

    try:
        payload = _post_form(TOKEN_ENDPOINT, {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }, timeout=timeout)
    except Exception as exc:
        return False, _friendly_error(exc)

    refresh = payload.get("refresh_token", "")
    access = payload.get("access_token", "")
    if not refresh:
        return False, ("Google did not return a refresh token. Remove the bot's "
                       "access at myaccount.google.com/permissions and try again "
                       "(the consent screen must be shown).")

    email = ""
    if access:
        try:
            req = urllib.request.Request(
                USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access}"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                email = json.loads(resp.read().decode("utf-8", "ignore")).get("email", "")
        except Exception:
            email = ""

    _set(KEY_REFRESH, refresh)
    if email:
        _set(KEY_EMAIL, email)
    expires_in = int(payload.get("expires_in", 3500) or 3500)
    _TOKEN_CACHE.update({
        "token": access,
        "expires_at": time.time() + max(60, expires_in - _EXPIRY_SKEW),
        "email": email,
    })
    return True, {"email": email, "refresh_token": refresh}


def access_token(timeout=20):
    """Return a valid access token, refreshing it when needed.

    Raises ``RuntimeError`` with a readable message when the login is gone
    (revoked, password changed, or the refresh token was never granted).
    """
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"]:
        return _TOKEN_CACHE["token"]

    refresh = _get(KEY_REFRESH)
    if not refresh:
        raise RuntimeError("Google Login is not connected yet.")
    client_id, client_secret = client_credentials()
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth client credentials are missing.")

    try:
        payload = _post_form(TOKEN_ENDPOINT, {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(_friendly_error(exc))

    token = payload.get("access_token", "")
    if not token:
        raise RuntimeError("Google returned no access token.")
    expires_in = int(payload.get("expires_in", 3500) or 3500)
    _TOKEN_CACHE.update({
        "token": token,
        "expires_at": now + max(60, expires_in - _EXPIRY_SKEW),
        "email": _TOKEN_CACHE.get("email") or _get(KEY_EMAIL),
    })
    return token


# ---------------------------------------------------------------------------
# step 3 - IMAP XOAUTH2
# ---------------------------------------------------------------------------
def xoauth2_string(user, token):
    """Build the SASL XOAUTH2 payload IMAP expects."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def imap_login(mail, user, timeout=20):
    """Authenticate an already-open IMAP connection using OAuth.

    Returns the email address that was used.  Raises on failure so the caller
    can fall back to an App Password.
    """
    token = access_token(timeout=timeout)
    payload = xoauth2_string(user, token).encode()
    mail.authenticate("XOAUTH2", lambda _challenge: payload)
    return user


def oauth_account_email():
    """Best-effort: which Gmail address this login belongs to."""
    return connected_email() or _TOKEN_CACHE.get("email", "")


def status_text():
    """One-line status for the admin panel."""
    if not has_client():
        return "\u274C Not set up (no OAuth client)"
    if not has_refresh_token():
        return "\u26A0\uFE0F Client saved, Google login pending"
    email = connected_email() or "connected"
    return f"\u2705 Connected as {email}"
