"""Gmail IMAP helpers for Auto-UPI verification.

Supports **multiple** Gmail accounts at once.  The owner can paste several
``email + app password`` pairs in one message and every one of them is stored
and scanned.  Earlier versions only ever remembered the first address, so a
second account's app password was glued onto the first one and the login
failed with ``AUTHENTICATIONFAILED`` -- the "app password catcher" bug.
"""

import imaplib
import os
import ssl
import email
import email.utils
import datetime
import json
import re
import asyncio
from database import cur, db
from config import logger

# How many recent messages to inspect locally when the server-side TEXT search
# comes back empty (Gmail indexes can lag by a minute or two).
LOCAL_SCAN_LIMIT = 40


def _setting(key):
    """Read one key from the ``settings`` table, tolerating a broken DB.

    Falls back to the runtime-config cache (same sqlite file) and finally to
    the environment.  A closed/locked database must never make the Auto-UPI
    gateway look "unconfigured" with a confusing crash.
    """
    try:
        row = cur.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if row and row[0] is not None and str(row[0]).strip():
            return str(row[0]).strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("IMAP setting read failed (%s): %s", key, exc)
    try:
        from utils import runtime_config

        value = runtime_config.get(key, "")
        if value:
            return value
    except Exception:
        pass
    return ""


def clean_app_password(pwd: str) -> str:
    """Normalise a Gmail App Password.

    Google *displays* app passwords as ``abcd efgh ijkl mnop`` (with spaces).
    IMAP only accepts the 16 characters glued together, so a copy-pasted
    password used to fail with ``AUTHENTICATIONFAILED``.  Strip every kind of
    whitespace (spaces, tabs, newlines, non-breaking spaces) and any wrapping
    quotes the user may have pasted along with it.
    """
    if not pwd:
        return ""
    cleaned = re.sub(r"[\s\u00a0\u200b\u200c\u200d\ufeff]+", "", str(pwd))
    return cleaned.strip("\"'`")


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Labels people paste along with the credentials ("Email:", "Pass:", "pwd" ...)
_LABEL_RE = re.compile(
    r"(?i)\b(?:e-?mail(?:\s*(?:id|address))?|app\s*pass(?:word)?|pass(?:word)?|pwd|"
    r"user(?:name)?|login|account|id)\b\s*[:=\-]?\s*"
)

# Characters that are almost never part of an app password but get pasted
# along with it (commas, quotes, brackets, bullets, ...).
_EDGE_JUNK = " \t\r\n\u00a0\"'`.,;:|/\\-_=+*#<>()[]{}\u2022\u2013\u2014"


def _clean_fragment(fragment: str) -> str:
    """Turn a raw chunk of pasted text into a bare app password."""
    if not fragment:
        return ""
    text = _LABEL_RE.sub(" ", str(fragment))
    return clean_app_password(text).strip(_EDGE_JUNK)


def parse_gmail_accounts(text):
    """Extract **every** ``(email, app_password)`` pair from pasted text.

    Handles all the shapes the owner realistically sends::

        you@example.com abcd efgh ijkl mnop
        Email: you@example.com Pass: abcd efgh ijkl mnop
        a@example.com abcd efgh ijkl mnop
        b@example.com wxyz wxyz wxyz wxyz
        abcd efgh ijkl mnop you@example.com      (password first)

    The password for each address is whatever text sits between that address
    and the next one, with labels/whitespace/punctuation stripped.  Returns a
    list of unique ``(email, password)`` tuples; an empty list when no address
    could be found.
    """
    raw = "" if text is None else str(text)
    matches = list(EMAIL_RE.finditer(raw))
    if not matches:
        return []

    accounts = []
    seen = set()
    for idx, match in enumerate(matches):
        addr = match.group(0).strip().strip(".,;:")
        after_start = match.end()
        after_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        password = _clean_fragment(raw[after_start:after_end])

        # Password may have been typed *before* the address (first pair only).
        if not password and idx == 0:
            password = _clean_fragment(raw[: match.start()])

        key = addr.lower()
        if key in seen:
            # Keep the first non-empty password we found for this address.
            continue
        seen.add(key)
        accounts.append((addr, password))
    return accounts


def parse_gmail_credentials(text):
    """Backwards-compatible single-pair parser.

    Returns ``("", "")`` when no email could be found.
    """
    accounts = parse_gmail_accounts(text)
    if not accounts:
        return "", ""
    return accounts[0]


# ---------------------------------------------------------------------------
# Storage: a JSON list under ``gmail_accounts`` plus the legacy single pair.
# ---------------------------------------------------------------------------

ACCOUNTS_KEY = "gmail_accounts"


def _load_accounts_json():
    raw = _setting(ACCOUNTS_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    accounts = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                user, pwd = item[0], item[1]
            elif isinstance(item, dict):
                user = item.get("user") or item.get("email") or ""
                pwd = item.get("pass") or item.get("password") or ""
            else:
                continue
            user = str(user or "").strip()
            pwd = clean_app_password(pwd)
            if user and pwd:
                accounts.append((user, pwd))
    return accounts


def save_gmail_accounts(accounts):
    """Persist a list of ``(email, password)`` pairs.

    Also refreshes the legacy ``gmail_user`` / ``gmail_pass`` keys with the
    first account so older code paths keep working.  Returns the number of
    accounts actually stored.
    """
    cleaned = []
    seen = set()
    for item in accounts or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            user, pwd = item[0], item[1]
        else:
            continue
        user = str(user or "").strip()
        pwd = clean_app_password(pwd)
        if not user or not pwd:
            continue
        key = user.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append([user, pwd])

    payload = json.dumps(cleaned, ensure_ascii=False)
    try:
        cur.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (ACCOUNTS_KEY, payload),
        )
        if cleaned:
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_user', ?)",
                (cleaned[0][0],),
            )
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_pass', ?)",
                (cleaned[0][1],),
            )
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Saving Gmail accounts failed: %s", exc)
        return 0

    try:
        from utils import runtime_config

        runtime_config.set(ACCOUNTS_KEY, payload)
    except Exception:
        pass
    return len(cleaned)


def get_imap_accounts():
    """Return every configured ``(email, password)`` pair, de-duplicated.

    Order of precedence: the JSON list, then the legacy single pair, then the
    environment.  Entries without a password are ignored because they can
    never log in.
    """
    accounts = []
    seen = set()

    def _add(user, pwd):
        user = str(user or "").strip()
        pwd = clean_app_password(pwd)
        if not user or not pwd:
            return
        key = user.lower()
        if key in seen:
            return
        seen.add(key)
        accounts.append((user, pwd))

    for user, pwd in _load_accounts_json():
        _add(user, pwd)

    _add(_setting("gmail_user"), _setting("gmail_pass"))
    _add(os.getenv("IMAP_USER", ""), os.getenv("IMAP_PASS", ""))
    return accounts


def get_imap_credentials():
    """Return the first configured Gmail IMAP login (backwards compatible).

    Returns ``("", "")`` when nothing is configured; callers must treat that
    as "gateway not configured" instead of attempting a login.
    """
    accounts = get_imap_accounts()
    if accounts:
        return accounts[0]
    return "", ""


def _imap_host_port():
    """Resolve the IMAP server from settings, with sane Gmail defaults."""
    host = (_setting("imap_host") or "imap.gmail.com").strip()
    raw_port = (_setting("imap_port") or "993").strip()
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 993
    return host, port


def _open_imap(user, pwd, timeout=20):
    """Open and log in to one mailbox.  Raises on failure."""
    host, port = _imap_host_port()
    context = ssl.create_default_context()
    mail = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=timeout)
    try:
        mail.login(user, pwd)
    except Exception:
        try:
            mail.logout()
        except Exception:
            pass
        raise
    return mail, host, port


def _explain_imap_error(exc, host, port):
    """Turn an IMAP/SSL exception into a human readable sentence."""
    raw = str(exc)
    low = raw.lower()
    if isinstance(exc, imaplib.IMAP4.error):
        if ("authenticationfailed" in low or "invalid credentials" in low
                or "username and password not accepted" in low):
            return ("Gmail rejected the login. Make sure 2-Step Verification is ON "
                    "and you are using a 16-character App Password "
                    "(not your normal Gmail password).")
        if "application-specific password required" in low:
            return "Gmail requires an App Password for this account (2FA is enabled)."
        return f"IMAP error: {raw}"
    if isinstance(exc, (ssl.SSLError, OSError)):
        return f"Network/SSL error connecting to {host}:{port} \u2014 {exc}"
    return f"{type(exc).__name__}: {exc}"


def _sync_test_connection(timeout=20):
    """Open a real IMAP session for every configured account.

    Returns ``(True, {...})`` on the first success, or ``(False, "reason")``
    when every account fails.  Never raises: the admin panel must always get a
    usable answer.
    """
    accounts = get_imap_accounts()
    if not accounts:
        return False, ("IMAP is not configured yet. Use "
                       "Admin Panel \u2192 Auto-UPI / IMAP \u2192 Change Gmail first.")

    host, port = _imap_host_port()
    errors = []
    for user, pwd in accounts:
        mail = None
        try:
            mail, host, port = _open_imap(user, pwd, timeout=timeout)
            total = 0
            try:
                status, data = mail.select("INBOX", readonly=True)
                if status == "OK" and data and data[0]:
                    total = int(str(data[0]).strip() or 0)
            except Exception:
                total = 0
            return True, {
                "user": user,
                "host": host,
                "port": port,
                "total": total,
                "accounts": len(accounts),
            }
        except Exception as exc:  # pragma: no cover - network dependent
            errors.append(f"{user}: {_explain_imap_error(exc, host, port)}")
        finally:
            try:
                if mail is not None:
                    mail.logout()
            except Exception:
                pass

    if len(errors) == 1:
        return False, errors[0]
    return False, "All accounts failed:\n" + "\n".join(f"\u2022 {e}" for e in errors)


async def test_imap_connection(timeout=20):
    """Async wrapper so the bot's event loop is never blocked by IMAP."""
    return await asyncio.to_thread(_sync_test_connection, timeout)


def imap_status():
    """Small helper for the admin panel: is the gateway usable?"""
    accounts = get_imap_accounts()
    user = accounts[0][0] if accounts else ""
    return {
        "configured": bool(accounts),
        "user": user,
        "accounts": len(accounts),
        "host": _setting("imap_host") or "imap.gmail.com",
        "port": _setting("imap_port") or "993",
    }

# Strict whitelist of official FamPay / Payment provider domains
OFFICIAL_SENDER_DOMAINS = [
    "@famapp.in",
    "@fampay.in",
    "@famapp.co.in",
    "no-reply@famapp.in"
]

# Maximum allowed age for auto-verification email (in minutes)
# Strict 30-minute window to completely block old payments/emails from past days!
MAX_PAYMENT_AGE_MINUTES = 30


def _message_body(msg):
    """Flatten a MIME message into plain text."""
    body = ""
    if msg.is_multipart():
        for p in msg.walk():
            payload = p.get_payload(decode=True)
            if payload:
                body += payload.decode(errors="ignore") + " "
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="ignore")
    text = re.sub("<[^<]+?>", " ", body)
    return re.sub(r"\s+", " ", text)


def _match_utr_in_message(msg, utr_clean, now_utc, max_age_mins):
    """Inspect one message.  Returns a result dict, or ``None`` to keep going.

    Crucially this never aborts the whole scan: a single old or unrelated
    message must not hide a valid payment further down the list.
    """
    # 1. STRICT SENDER AUTHENTICATION: must come from an official sender.
    from_header = (msg.get("From") or "").lower()
    if not any(domain in from_header for domain in OFFICIAL_SENDER_DOMAINS):
        logger.warning("Ignored fake/unauthorized payment email from: %s", from_header)
        return None

    # 2. STRICT DATE / EXPIRATION CHECK: prevent reusing old payments.
    date_header = msg.get("Date")
    if date_header:
        try:
            email_dt = email.utils.parsedate_to_datetime(date_header)
            if email_dt.tzinfo is None:
                email_dt = email_dt.replace(tzinfo=datetime.timezone.utc)
            age_minutes = (now_utc - email_dt.astimezone(
                datetime.timezone.utc)).total_seconds() / 60.0
            if age_minutes > max_age_mins:
                logger.warning(
                    "Skipped old UTR %s: email date was %s (%.1f mins old, limit %s)",
                    utr_clean, email_dt, age_minutes, max_age_mins)
                return None
        except Exception as dt_err:
            logger.error("Error parsing email date: %s", dt_err)

    clean_text = _message_body(msg)
    if utr_clean.lower() not in clean_text.lower():
        return None

    msg_id = (msg.get("Message-ID") or "").strip()

    amt_match = re.search(r"received\s*\u20b9\s*([0-9]+(?:\.[0-9]+)?)", clean_text, re.I)
    if not amt_match:
        amt_match = re.search(r"\u20b9\s*([0-9]+(?:\.[0-9]+)?)", clean_text)
    amt = float(amt_match.group(1)) if amt_match else 0.0

    sender_match = re.search(r"from\s+([^.]+?)\s*(?:\.|\sat|\swith)", clean_text, re.I)
    sender = sender_match.group(1).strip() if sender_match else "User"

    utr_match = re.search(r"UTR[:\s]*([0-9]{6,15})", clean_text, re.I)
    detected_utr = utr_match.group(1).strip() if utr_match else (
        utr_clean if utr_clean.isdigit() else "")

    txnid_match = re.search(r"transaction\s*id[:\s]*([A-Za-z0-9]+)", clean_text, re.I)
    detected_txnid = txnid_match.group(1).strip() if txnid_match else (
        utr_clean if not utr_clean.isdigit() else "")

    return {
        "utr": utr_clean,
        "email_msg_id": msg_id,
        "detected_utr": detected_utr,
        "detected_txnid": detected_txnid,
        "amount": int(amt) if amt == int(amt) else amt,
        "sender": sender,
        "raw": clean_text[:200],
    }


def _scan_mailbox(mail, utr_clean, now_utc, max_age_mins):
    """Search one logged-in mailbox for the UTR.  Returns a result or ``None``."""
    mail_ids = []

    since_date = (now_utc - datetime.timedelta(days=1)).strftime("%d-%b-%Y")
    try:
        status, data = mail.search(None, f'(SINCE "{since_date}" TEXT "{utr_clean}")')
        if status == "OK" and data and data[0]:
            mail_ids = data[0].split()
    except Exception as exc:
        logger.warning("IMAP date search failed: %s", exc)

    if not mail_ids:
        try:
            status, data = mail.search(None, f'(TEXT "{utr_clean}")')
            if status == "OK" and data and data[0]:
                mail_ids = data[0].split()
        except Exception as exc:
            logger.warning("IMAP text search failed: %s", exc)

    if not mail_ids:
        # Local fallback: Gmail's index can lag, so look at the newest messages.
        try:
            status, data = mail.select("INBOX", readonly=True)
            if status == "OK" and data and data[0]:
                total = int(str(data[0]).strip() or 0)
                if total > 0:
                    start = max(1, total - LOCAL_SCAN_LIMIT + 1)
                    status, data = mail.fetch(f"{start}:{total}", "(RFC822)")
                    if status == "OK" and data:
                        for part in data:
                            if isinstance(part, tuple):
                                msg = email.message_from_bytes(part[1])
                                hit = _match_utr_in_message(
                                    msg, utr_clean, now_utc, max_age_mins)
                                if hit:
                                    return hit
        except Exception as exc:
            logger.warning("IMAP local scan failed: %s", exc)
        return None

    for m_id in reversed(mail_ids[-25:]):
        try:
            status, msg_data = mail.fetch(m_id, "(RFC822)")
        except Exception as exc:
            logger.warning("IMAP fetch failed for %s: %s", m_id, exc)
            continue
        if status != "OK" or not msg_data:
            continue
        for part in msg_data:
            if isinstance(part, tuple):
                msg = email.message_from_bytes(part[1])
                hit = _match_utr_in_message(msg, utr_clean, now_utc, max_age_mins)
                if hit:
                    return hit
    return None


def _sync_verify_utr(utr_query, max_age_mins=MAX_PAYMENT_AGE_MINUTES):
    accounts = get_imap_accounts()
    if not accounts:
        return False, "Gateway configuration error."

    utr_clean = (utr_query or "").strip()
    if len(utr_clean) < 6:
        return False, "Invalid UTR / Transaction ID length."

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    errors = []
    for user, pwd in accounts:
        mail = None
        try:
            mail, _host, _port = _open_imap(user, pwd, timeout=25)
            try:
                mail.select("INBOX")
            except Exception:
                pass
            hit = _scan_mailbox(mail, utr_clean, now_utc, max_age_mins)
            if hit:
                return True, hit
        except Exception as exc:
            logger.error("IMAP verification failed for %s: %s", user, exc)
            errors.append(str(exc))
        finally:
            try:
                if mail is not None:
                    mail.logout()
            except Exception:
                pass

    if errors and len(errors) == len(accounts):
        logger.error("IMAP verification exception: %s", "; ".join(errors))
        return False, "Payment verification server error."
    return False, "Payment not found or not settled yet."


async def verify_payment_utr(utr_query, max_age_mins=MAX_PAYMENT_AGE_MINUTES):
    """Asynchronous wrapper for IMAP payment verification."""
    return await asyncio.to_thread(_sync_verify_utr, utr_query, max_age_mins)
