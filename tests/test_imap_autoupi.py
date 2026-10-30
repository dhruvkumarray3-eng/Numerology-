"""Regression tests for the Auto-UPI / IMAP gateway and the Recharge menu.

Covers the three bugs reported from the live bot:

1. "Test IMAP" did nothing  -> the login ran inline on the event loop and the
   callback query timed out.  The handler must now offload to a thread and be
   wrapped in ``asyncio.wait_for``.
2. "I set IMAP but it never tested"  -> a copy-pasted Gmail App Password keeps
   the spaces Google displays (``abcd efgh ijkl mnop``), which makes
   ``imaplib`` fail with AUTHENTICATIONFAILED.  Passwords must be normalised.
3. "Recharge never offered that method"  -> ``deposit_menu`` only rendered the
   USDT (BEP-20) button, so the UPI / Auto-verify flow was unreachable.
"""

import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2705 {name}")
    else:
        FAIL += 1
        print(f"  \u274c {name} {extra}")


def section(title):
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
section("1. App password normalisation")
from utils.imap_verifier import clean_app_password, get_imap_credentials

check("spaces removed", clean_app_password("dqwo agxp srsw fdax") == "dqwoagxpsrswfdax")
check("newlines/tabs removed", clean_app_password("dqwo\nagxp\tsrsw fdax") == "dqwoagxpsrswfdax")
check("non-breaking space removed", clean_app_password("dqwo\u00a0agxp srsw fdax") == "dqwoagxpsrswfdax")
check("quotes stripped", clean_app_password('"dqwo agxp srsw fdax"') == "dqwoagxpsrswfdax")
check("empty stays empty", clean_app_password("") == "" and clean_app_password(None) == "")
check("already clean untouched", clean_app_password("dqwoagxpsrswfdax") == "dqwoagxpsrswfdax")

# ---------------------------------------------------------------------------
section("1b. parse_gmail_credentials handles real-world input")
from utils.imap_verifier import parse_gmail_credentials

cases = [
    # (input, expected email, expected password)
    ("neetasgaritsairlank@gmail.com cpe ungh swit limb", "neetasgaritsairlank@gmail.com", "cpeunghswitlimb"),
    ("neetasgaritsairlank@gmail.com expe ungh swit limb.", "neetasgaritsairlank@gmail.com", "expeunghswitlimb"),
    ("neetasgaritsairlank@gmail.com", "neetasgaritsairlank@gmail.com", ""),
    ("  \n neetasgaritsairlank@gmail.com   dqwo agxp srsw fdax \n ", "neetasgaritsairlank@gmail.com", "dqwoagxpsrswfdax"),
    ("dqwo agxp srsw fdax neetasgaritsairlank@gmail.com", "neetasgaritsairlank@gmail.com", "dqwoagxpsrswfdax"),
    ("Email: neetasgaritsairlank@gmail.com Pass: dqwo agxp srsw fdax", "neetasgaritsairlank@gmail.com", "dqwoagxpsrswfdax"),
    ("neetasgaritsairlank@gmail.com, dqwo agxp srsw fdax", "neetasgaritsairlank@gmail.com", "dqwoagxpsrswfdax"),
    ("not an email at all", "", ""),
    ("", "", ""),
    (None, "", ""),
]
for raw, want_mail, want_pass in cases:
    got_mail, got_pass = parse_gmail_credentials(raw)
    label = repr(raw)[:46]
    check(f"parse {label} -> email", got_mail == want_mail, f"{got_mail!r} != {want_mail!r}")
    check(f"parse {label} -> pass", got_pass == want_pass, f"{got_pass!r} != {want_pass!r}")

# ---------------------------------------------------------------------------
section("1c. Multiple accounts in one message are all captured")
from utils.imap_verifier import parse_gmail_accounts
from database import cur, db

multi = parse_gmail_accounts(
    "first@gmail.com abcd efgh ijkl mnop\n"
    "second@gmail.com wxyz wxyz wxyz wxyz")
check("two accounts parsed", len(multi) == 2, multi)
check("first account", multi[0] == ("first@gmail.com", "abcd efgh ijkl mnop".replace(" ", "")), multi[0])
check("second account", multi[1] == ("second@gmail.com", "wxyzwxyzwxyzwxyz"), multi[1])

labelled = parse_gmail_accounts(
    "Email: a@gmail.com Pass: abcd efgh ijkl mnop\n"
    "Email: b@gmail.com Pass: wxyz wxyz wxyz wxyz")
check("labelled multi parsed", len(labelled) == 2, labelled)
check("labelled first password clean", labelled[0][1] == "abcdefghijklmnop", labelled[0])
check("labelled second password clean", labelled[1][1] == "wxyzwxyzwxyzwxyz", labelled[1])

check("single email no password", parse_gmail_accounts("a@gmail.com") == [("a@gmail.com", "")])
check("no email -> empty list", parse_gmail_accounts("nothing here") == [])
check("duplicate email collapsed", len(parse_gmail_accounts(
    "a@gmail.com abcd efgh ijkl mnop a@gmail.com wxyz wxyz wxyz wxyz")) == 1)

# Round-trip through the settings table
from utils.imap_verifier import save_gmail_accounts, get_imap_accounts
saved = save_gmail_accounts([("one@gmail.com", "abcd efgh ijkl mnop"),
                             ("two@gmail.com", "wxyz wxyz wxyz wxyz")])
check("two accounts saved", saved == 2, saved)
back = get_imap_accounts()
check("two accounts read back", len(back) == 2, back)
check("legacy gmail_user points at first", back[0][0] == "one@gmail.com", back)
cur.execute("DELETE FROM settings WHERE key='gmail_accounts'")
db.commit()

# The exact screenshot failure: an email alone must never yield an empty
# "Got:" line again.
m, pw = parse_gmail_credentials("neetasgaritsairlank@gmail.com")
check("screenshot email alone is recognised", m == "neetasgaritsairlank@gmail.com", m)
check("screenshot email alone has no password", pw == "", pw)


# ---------------------------------------------------------------------------
section("2. Credentials are read back cleaned from the settings table")
import database
from database import cur, db

cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_user', ?)",
            ("owner.test@gmail.com",))
cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_pass', ?)",
            ("dqwo agxp srsw fdax",))
db.commit()

u, p = get_imap_credentials()
check("email read", u == "owner.test@gmail.com", u)
check("password de-spaced", p == "dqwoagxpsrswfdax", p)
check("password is 16 chars", len(p) == 16, len(p))

# ---------------------------------------------------------------------------
section("3. test_imap_connection never raises and explains failures")
from utils.imap_verifier import test_imap_connection, _sync_test_connection

# Force a guaranteed-failure login: valid shape, wrong credentials.
cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_pass', ?)",
            ("aaaabbbbccccdddd",))
db.commit()

ok, res = _sync_test_connection(timeout=15)
check("returns a tuple", isinstance(ok, bool) and (isinstance(res, dict) or isinstance(res, str)))
check("wrong password -> not ok", ok is False, res)
check("reason is human readable", isinstance(res, str) and len(res) > 10, res)
print(f"     reason: {res}")

# Not configured at all
cur.execute("DELETE FROM settings WHERE key='gmail_user'")
cur.execute("DELETE FROM settings WHERE key='gmail_pass'")
db.commit()
os.environ.pop("IMAP_USER", None)
os.environ.pop("IMAP_PASS", None)

ok2, res2 = _sync_test_connection(timeout=5)
check("unconfigured -> not ok", ok2 is False, res2)
check("unconfigured message mentions Change Gmail",
      "Change Gmail" in res2 or "not configured" in res2.lower(), res2)

# Async wrapper works and does not block the loop
async def _async_probe():
    return await test_imap_connection(timeout=5)

ok3, res3 = asyncio.run(_async_probe())
check("async wrapper returns same shape", ok3 is False and isinstance(res3, str), res3)

# ---------------------------------------------------------------------------
section("4. Admin panel handlers are non-blocking and validating")
src = io.open("plugins/admin_actions.py", encoding="utf-8").read()

test_block_start = src.index('elif action_data == "test_imap"')
test_block = src[test_block_start:test_block_start + 1400]
check("test_imap uses asyncio.wait_for", "asyncio.wait_for" in test_block)
check("test_imap uses test_imap_connection", "test_imap_connection" in test_block)
check("test_imap has no inline imaplib login", "mail.login" not in test_block)
check("test_imap handles timeout", "TimeoutError" in test_block)

gm_start = src.index('elif action_data == "change_gmail"')
gm_block = src[gm_start:gm_start + 7000]
check("change_gmail uses the shared parser", "parse_gmail_accounts" in gm_block)
check("change_gmail normalises password", "clean_app_password" in gm_block)
check("change_gmail retries bad input", "for attempt in range(3)" in gm_block)
check("change_gmail warns on odd password length", "len(pwd) != 16" in gm_block)
check("change_gmail auto-tests after save", "test_imap_connection" in gm_block)
check("change_gmail saves every account", "save_gmail_accounts" in gm_block)
check("change_gmail escapes echoed input", "html.escape(text[:80])" in gm_block)

# The prompt must not contain a raw "<placeholder>" tag: Telegram's HTML
# parser strips unknown tags, which is what mangled the "Format:" line.
code_only = "\n".join(
    ln for ln in gm_block.splitlines() if not ln.strip().startswith("#")
)
import re as _re
raw_tags = _re.findall(r"<(?!/?(?:b|i|u|s|code|pre|a|blockquote|tg-spoiler)\b)[a-zA-Z][^>]*>", code_only)
check("change_gmail prompt has no raw placeholder tag", not raw_tags, raw_tags)

# ---------------------------------------------------------------------------
section("5. Recharge menu exposes the UPI / Auto-verify method")
dsrc = io.open("plugins/deposit.py", encoding="utf-8").read()

menu_start = dsrc.index("async def deposit_menu(event):")
menu_end = dsrc.index("def _bep20_qr_bytes", menu_start)
menu = dsrc[menu_start:menu_end]

check("menu offers UPI button", "dep_choose_UPI" in menu)
check("menu still offers USDT BEP-20", "dep_choose_BEP20" in menu)
check("menu reads live upi_id from settings", "key='upi_id'" in menu)
check("menu hides UPI when unset", "if active_upi:" in menu)

# The generic chooser must accept dep_choose_UPI
check("generic chooser accepts UPI",
      'r"^dep_choose_(?!BEP20$)(.+)$"' in dsrc)

# ---------------------------------------------------------------------------
section("6. Functional: deposit_menu renders the right buttons")
from plugins.deposit import deposit_menu

class _FakeEvent:
    def __init__(self):
        self.buttons = None
        self.text = None

    async def respond(self, text, buttons=None):
        self.text = text
        self.buttons = buttons

    async def edit(self, text, buttons=None):
        self.text = text
        self.buttons = buttons


def _flat(btns):
    out = []
    for row in btns or []:
        for b in row:
            data = getattr(b, "data", b"")
            if isinstance(data, bytes):
                data = data.decode(errors="ignore")
            out.append((getattr(b, "text", ""), data))
    return out


# With a UPI id configured
cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)",
            ("owner@fam",))
db.commit()
ev = _FakeEvent()
asyncio.run(deposit_menu(ev))
flat = _flat(ev.buttons)
datas = [d for _, d in flat]
check("UPI button present when upi_id set", "dep_choose_UPI" in datas, datas)
check("BEP20 button present", "dep_choose_BEP20" in datas, datas)
check("back button present", "dashboard_main" in datas, datas)
check("UPI id shown in text", "owner@fam" in ev.text)

# With no UPI id configured -> UPI button hidden, menu still works
cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", ("",))
db.commit()
ev2 = _FakeEvent()
asyncio.run(deposit_menu(ev2))
datas2 = [d for _, d in _flat(ev2.buttons)]
check("UPI hidden when no upi_id", "dep_choose_UPI" not in datas2, datas2)
check("BEP20 still available", "dep_choose_BEP20" in datas2, datas2)

# restore
cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)",
            ("owner@fam",))
db.commit()

# ---------------------------------------------------------------------------
# 8. Login hardening (v17)
# ---------------------------------------------------------------------------
from utils.imap_verifier import (
    password_candidates, _mailbox_count, _is_gmail, _endpoints_for,
    _sender_allowed, _looks_like_payment, _is_auth_error, probe_network,
)

# Gmail always shows app passwords in lowercase; a caps-typed one must still work.
check("caps password gets a lowercase candidate",
      "siyyziefwytprtku" in password_candidates("SIYY ZIEF WYTP RTKU"),
      password_candidates("SIYY ZIEF WYTP RTKU"))
check("spaced password glued first",
      password_candidates("siyy zief wytp rtku")[0] == "siyyziefwytprtku")

# imaplib returns bytes; str(b'1751') used to break int() and report 0 emails.
check("mailbox count from bytes", _mailbox_count(b"1751") == 1751)
check("mailbox count from quoted bytes", _mailbox_count(b'"INBOX" 42') == 42)
check("mailbox count None", _mailbox_count(None) == 0)

# Gmail addresses must always hit imap.gmail.com, never a stale setting.
check("gmail detected", _is_gmail("someone@gmail.com"))
check("googlemail detected", _is_gmail("someone@googlemail.com"))
check("non-gmail detected", not _is_gmail("someone@yahoo.com"))
eps = _endpoints_for("someone@gmail.com")
check("gmail endpoint is imap.gmail.com:993", eps[0] == ("imap.gmail.com", 993, False), eps)
check("gmail has STARTTLS fallback", any(e[2] for e in eps), eps)

# Sender gate: known app, unknown bank domain, brand-only display name.
check("phonepe allowed", _sender_allowed("PhonePe <noreply@phonepe.com>"))
check("fampay allowed", _sender_allowed("FamPay <no-reply@famapp.in>"))
check("unknown bank domain allowed",
      _sender_allowed("Alerts <alerts@somecoopbank.co.in>"))
check("brand in display name allowed",
      _sender_allowed('"Google Pay" <x@randomdomain.xyz>'))
check("plain promo blocked", not _sender_allowed("Shop <promo@shop.com>"))

# Body fallback so an unexpected sender is still honoured.
check("body fallback credit+amount",
      _looks_like_payment("Rs.500 has been credited to your account"))
check("body fallback ref only",
      _looks_like_payment("Rs.500 UTR 412345678901"))
check("body fallback rejects noise", not _looks_like_payment("Big sale today"))

# Auth vs network errors must be distinguished.
check("auth error detected",
      _is_auth_error(Exception("[AUTHENTICATIONFAILED] Invalid credentials")))
check("network error not auth",
      not _is_auth_error(OSError("Network is unreachable")))

# probe_network returns one row per endpoint without raising.
probe = probe_network("someone@gmail.com", timeout=1)
check("probe_network rows", len(probe) == len(eps), probe)
check("probe_network shape", all(len(r) == 3 for r in probe), probe)

# ---------------------------------------------------------------------------
print(f"\n{PASS} passed, {FAIL} failed")
if FAIL:
    print("=== SOME TESTS FAILED ===")
    sys.exit(1)
print("=== ALL TESTS PASSED ===")
