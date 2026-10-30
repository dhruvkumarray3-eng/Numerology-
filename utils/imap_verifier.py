"""Gmail IMAP helpers for Auto-UPI verification.

Two things this module has to get right:

1. **Logging in with a real Gmail App Password.**  Google shows app passwords
   as ``abcd efgh ijkl mnop`` (16 lowercase letters in four groups).  People
   paste them with labels, line breaks, trailing dots, sometimes twice.  This
   module now *extracts* the 16-letter password out of whatever was pasted and,
   if the stored value still looks wrong, tries a short list of repaired
   variants against Gmail before giving up.  When a variant works it is handed
   back so the caller can persist the repaired value.

2. **Reading real payment notifications.**  Auto-UPI is not only FamPay: money
   arrives via PhonePe, Google Pay, Paytm, BHIM, Amazon Pay, Mobikwik, CRED
   and straight from bank alert emails.  ``DEFAULT_SENDER_DOMAINS`` covers all
   of them (and is overridable from the settings table), and the amount /
   reference-number parser understands the wording those mails actually use.

Multiple Gmail accounts are supported: every ``email + app password`` pair
found in one pasted message is stored and every mailbox is scanned.
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

# A Gmail app password is exactly 16 letters, usually shown as 4 x 4.
_APP_PWD_GROUPED = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{4}[ \t\r\n]+){3}[A-Za-z]{4}(?![A-Za-z0-9])"
)
_APP_PWD_PLAIN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{16}(?![A-Za-z0-9])")


def extract_app_password(fragment: str) -> str:
    """Find a Gmail-shaped 16-letter app password inside pasted text.

    Returns ``""`` when the text does not contain one.  This is what makes the
    catcher reliable: instead of trusting the whole leftover blob, we look for
    the actual shape Google uses.
    """
    if not fragment:
        return ""
    text = str(fragment)
    match = _APP_PWD_GROUPED.search(text)
    if match:
        return clean_app_password(match.group(0))
    match = _APP_PWD_PLAIN.search(text)
    if match:
        return match.group(0)
    return ""


def _clean_fragment(fragment: str) -> str:
    """Turn a raw chunk of pasted text into a bare app password."""
    if not fragment:
        return ""
    found = extract_app_password(fragment)
    if found:
        return found
    text = _LABEL_RE.sub(" ", str(fragment))
    return clean_app_password(text).strip(_EDGE_JUNK)


def password_candidates(pwd: str):
    """Return every plausible reading of a stored password, best first.

    Gmail app passwords are 16 letters.  If the stored value is longer (the
    owner pasted it twice, or pasted a label along with it) we still try the
    aligned 16-letter windows so a correct password is never rejected just
    because of surrounding junk.
    """
    base = clean_app_password(pwd)
    out = []

    def _add(value):
        if value and value not in out:
            out.append(value)

    _add(base)
    letters = re.sub(r"[^A-Za-z]", "", base)
    _add(letters)
    # Gmail always *shows* app passwords in lowercase.  If the owner typed them
    # in caps (or their keyboard auto-capitalised the first letter) the exact
    # value can never match, so try the lowercase reading too.
    _add(letters.lower())
    _add(base.lower())
    if len(letters) > 16:
        _add(letters[:16])
        _add(letters[-16:])
        _add(letters[:16].lower())
        _add(letters[-16:].lower())
        for start in range(0, len(letters) - 15, 4):
            window = letters[start:start + 16]
            _add(window)
            _add(window.lower())
    return out


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
        pwd = _clean_fragment(pwd) or clean_app_password(pwd)
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


def update_stored_password(user, new_password):
    """Replace the password for one account after a successful repair."""
    accounts = _load_accounts_json()
    changed = False
    for idx, (addr, _pwd) in enumerate(accounts):
        if addr.lower() == str(user).lower():
            accounts[idx] = (addr, clean_app_password(new_password))
            changed = True
    if not changed:
        accounts.append((str(user), clean_app_password(new_password)))
    save_gmail_accounts(accounts)
    # Keep the legacy pair in sync when it points at this account.
    if (_setting("gmail_user") or "").lower() == str(user).lower():
        try:
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_pass', ?)",
                (clean_app_password(new_password),),
            )
            db.commit()
        except Exception:
            pass
    return changed


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
    """Open and log in to one mailbox, trying repaired password variants.

    Returns ``(mail, host, port, used_password)``.  Raises the last error when
    every candidate is rejected, so the caller can explain it.
    """
    host, port = _imap_host_port()
    context = ssl.create_default_context()
    candidates = password_candidates(pwd)
    last_exc = None

    for candidate in candidates:
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=timeout)
            mail.login(user, candidate)
            return mail, host, port, candidate
        except Exception as exc:
            last_exc = exc
            try:
                if mail is not None:
                    mail.logout()
            except Exception:
                pass
            low = str(exc).lower()
            # Only an auth failure is worth retrying with another variant.
            if ("authenticationfailed" not in low
                    and "invalid credentials" not in low
                    and "username and password not accepted" not in low
                    and "application-specific password required" not in low):
                raise
    if last_exc is not None:
        raise last_exc
    raise imaplib.IMAP4.error("AUTHENTICATIONFAILED no password candidates")


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

    On success the payload contains ``repaired_password`` when a variant other
    than the stored value was needed, so the caller can persist it.
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
            mail, host, port, used = _open_imap(user, pwd, timeout=timeout)
            total = 0
            try:
                status, data = mail.select("INBOX", readonly=True)
                if status == "OK" and data and data[0]:
                    total = int(str(data[0]).strip() or 0)
            except Exception:
                total = 0
            result = {
                "user": user,
                "host": host,
                "port": port,
                "total": total,
                "accounts": len(accounts),
            }
            if used != clean_app_password(pwd):
                result["repaired_password"] = used
            return True, result
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


# ---------------------------------------------------------------------------
# Sender whitelist
# ---------------------------------------------------------------------------
# Every UPI app and the big Indian banks send a payment alert email.  Auto-UPI
# used to accept *only* FamPay, which is why a perfectly valid PhonePe / GPay /
# bank credit was reported as "Payment not found".  Hybrid mode is supposed to
# read all of them.

DEFAULT_SENDER_DOMAINS = [
    # FamPay / FamApp
    "@famapp.in", "@fampay.in", "@famapp.co.in", "no-reply@famapp.in",
    # UPI apps
    "@phonepe.com", "@phonepe.in",
    "googlepay-noreply@google.com", "noreply@google.com",
    "@paytm.com", "@paytmbank.com",
    "@bhimupi.org.in", "@npci.org.in",
    "@amazonpay.in", "@amazon.in",
    "@mobikwik.com", "@freecharge.in", "@cred.club",
    "@sliceit.com", "@jupiter.money", "@navi.com",
    # Banks (alerts / transaction mails)
    "@hdfcbank.net", "@hdfcbank.com",
    "@icicibank.com", "@icicibank.net",
    "@sbi.co.in", "@onlinesbi.sbi", "@sbicard.com",
    "@axisbank.com", "@axisbank.co.in",
    "@kotak.com", "@kotakbank.com",
    "@pnb.co.in", "@bankofbaroda.com", "@bankofbaroda.in",
    "@idbibank.com", "@idfcfirstbank.com", "@yesbank.in",
    "@indusind.com", "@canarabank.com", "@unionbankofindia.co.in",
    "@federalbank.co.in", "@rblbank.com", "@aubank.in",
    "@bandhanbank.com", "@dbs.com", "@hsbc.co.in",
]

# Kept for backwards compatibility with older imports.
OFFICIAL_SENDER_DOMAINS = DEFAULT_SENDER_DOMAINS

# Maximum allowed age for auto-verification email (in minutes)
# Strict 30-minute window to completely block old payments/emails from past days!
MAX_PAYMENT_AGE_MINUTES = 30


def sender_domains():
    """Return the active whitelist: defaults **plus** any settings override.

    The override is additive on purpose.  Adding a custom sender from the admin
    panel must never silently drop PhonePe / GPay / FamPay / bank alerts, which
    is exactly what a plain "replace" would do.
    """
    domains = list(DEFAULT_SENDER_DOMAINS)
    raw = _setting("imap_sender_domains")
    if raw:
        for part in re.split(r"[,\s]+", raw):
            part = part.strip().lower()
            if part and part not in domains:
                domains.append(part)
    return domains


def _sender_allowed(from_header):
    """True when the From header looks like a UPI app, wallet or bank alert.

    Three tiers, cheapest first:

    1. exact domain in the whitelist (PhonePe, GPay, FamPay, 40+ banks);
    2. the domain itself contains ``bank`` / ``pay`` / ``upi`` / ``wallet``
       (catches the long tail: small co-op banks, payments banks, new apps);
    3. the display name mentions a known brand (``"PhonePe" <x@y.com>``).
    """
    header = (from_header or "").lower()
    if not header:
        return False
    for domain in sender_domains():
        if domain in header:
            return True
    addr = header.rsplit("<", 1)[-1].rstrip(">").strip()
    domain = addr.split("@")[-1] if "@" in addr else ""
    if any(word in domain for word in ("bank", "pay", "upi", "wallet", "fintech")):
        return True
    return any(brand in header for brand in (
        "phonepe", "google pay", "gpay", "famapp", "fampay", "paytm", "bhim",
        "amazon pay", "mobikwik", "freecharge", "cred", "slice", "jupiter",
        "navi", "hdfc", "icici", "sbi", "state bank", "axis", "kotak", "pnb",
        "bank of baroda", "idbi", "idfc", "yes bank", "indusind", "canara",
        "union bank", "federal bank", "rbl", "au bank", "bandhan", "dbs",
        "hsbc", "airtel payments", "jio payments", "india post payments",
    ))


_CREDIT_WORDS = (
    "credited", "credit", "received", "receive", "deposited", "deposit",
    "added to your", "money added", "payment successful", "paid to you",
    "has been credited", "successfully added", "incoming",
)


def _looks_like_payment(text):
    """Heuristic: does this body read like a money-received notification?

    Used as a fallback when the sender is not on the whitelist, so a bank alert
    from an unexpected domain is still honoured instead of silently dropped.
    """
    low = (text or "").lower()
    if not low:
        return False
    has_amount = bool(_AMOUNT_RE.search(low))
    has_credit = any(word in low for word in _CREDIT_WORDS)
    has_ref = bool(_REF_RE.search(text or ""))
    return has_amount and (has_credit or has_ref)


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------

# "Rs.500", "Rs 1,250.00", "INR 500", "\u20b9500"
_AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|\u20b9)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)

# Reference numbers used by UPI apps and banks.
_REF_RE = re.compile(
    r"(?:utr|rrn|upi\s*(?:ref(?:erence)?(?:\s*(?:no|number|id))?)?|"
    r"transaction\s*(?:id|no|number)|txn\s*(?:id|no|number)|"
    r"ref(?:erence)?\s*(?:no|number|id)?)\s*[:#\-]?\s*([A-Za-z0-9]{6,30})", re.I)


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


def _parse_amount(text):
    """Best-effort amount extraction, preferring a 'credited/received' amount."""
    for keyword in ("credited", "received", "credit", "deposit", "paid"):
        window = re.search(keyword, text, re.I)
        if window:
            snippet = text[max(0, window.start() - 160): window.end() + 160]
            match = _AMOUNT_RE.search(snippet)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    pass
    match = _AMOUNT_RE.search(text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    return 0.0


def _parse_references(text):
    """Collect every UTR / RRN / transaction id found in the body."""
    refs = []
    for match in _REF_RE.finditer(text):
        value = match.group(1).strip()
        if value and value not in refs:
            refs.append(value)
    return refs


def _utr_present(utr_clean, text, refs):
    """True when the user-supplied UTR appears in the mail or its refs."""
    needle = utr_clean.lower()
    if needle in text.lower():
        return True
    squashed = re.sub(r"[^a-z0-9]", "", needle)
    for ref in refs:
        if ref.lower() == needle:
            return True
        # Banks sometimes print the RRN with spaces / dashes inside.
        if re.sub(r"[^a-z0-9]", "", ref.lower()) == squashed:
            return True
    return False


def _match_utr_in_message(msg, utr_clean, now_utc, max_age_mins):
    """Inspect one message.  Returns a result dict, or ``None`` to keep going.

    Crucially this never aborts the whole scan: a single old or unrelated
    message must not hide a valid payment further down the list.
    """
    from_header = msg.get("From") or ""
    clean_text = _message_body(msg)
    if not _sender_allowed(from_header) and not _looks_like_payment(clean_text):
        logger.warning("Ignored payment email from unlisted sender: %s", from_header)
        return None

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

    refs = _parse_references(clean_text)
    if not _utr_present(utr_clean, clean_text, refs):
        return None

    msg_id = (msg.get("Message-ID") or "").strip()
    amt = _parse_amount(clean_text)

    sender_match = re.search(
        r"(?:from|paid by|sender)\s*[:\-]?\s*([A-Za-z][A-Za-z .]{2,40}?)\s*(?:\.|\sat|\swith|,|$)",
        clean_text, re.I)
    sender = sender_match.group(1).strip() if sender_match else "User"

    detected_utr = next((r for r in refs if r.isdigit()), "")
    detected_txnid = next((r for r in refs if not r.isdigit()), "")
    if utr_clean.isdigit() and not detected_utr:
        detected_utr = utr_clean
    if not utr_clean.isdigit() and not detected_txnid:
        detected_txnid = utr_clean

    return {
        "utr": utr_clean,
        "email_msg_id": msg_id,
        "detected_utr": detected_utr,
        "detected_txnid": detected_txnid,
        "amount": int(amt) if amt == int(amt) else amt,
        "sender": sender,
        "source": from_header[:120],
        "refs": refs[:6],
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
            mail, _host, _port, used = _open_imap(user, pwd, timeout=25)
            if used != clean_app_password(pwd):
                # The stored password was junk; remember the working one.
                try:
                    update_stored_password(user, used)
                except Exception:
                    pass
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
