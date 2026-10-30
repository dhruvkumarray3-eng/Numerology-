"""Regression tests for the Google Login (OAuth 2.0 / XOAUTH2) module.

Google no longer accepts a normal Gmail password for IMAP and rejects App
Passwords on many accounts, so the bot now ships a real "Sign in with Google"
flow.  These tests cover everything that can be verified without a live
Google account:

1. ``extract_code`` must survive every shape a user can paste (full redirect
   URL, ``code=`` fragment, bare code, quoted code, URL-encoded code).
2. ``auth_url`` must request offline access and force consent, otherwise
   Google returns no refresh token and IMAP breaks again an hour later.
3. ``xoauth2_string`` must produce the exact SASL payload IMAP expects.
4. ``exchange_code`` must fail *gracefully* (never raise) when the client is
   not configured or the pasted text has no code in it.
5. ``status_text`` must describe all three states truthfully.
"""

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


from utils import google_oauth as go  # noqa: E402

# ---------------------------------------------------------------------------
section("1. extract_code accepts every paste shape")
# ---------------------------------------------------------------------------
FULL_URL = "http://localhost/?code=4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx&scope=email"
check("full redirect URL", go.extract_code(FULL_URL) == "4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx",
      go.extract_code(FULL_URL))
check("URL with extra params before code",
      go.extract_code("http://localhost/?state=numerology&code=4/0AabcDEF123") == "4/0AabcDEF123")
check("code= fragment only",
      go.extract_code("code=4/0AZZZZ999") == "4/0AZZZZ999")
check("bare code", go.extract_code("4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx") ==
      "4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx")
check("quoted bare code", go.extract_code('"4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx"') ==
      "4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx")
check("url-encoded code is decoded",
      go.extract_code("http://localhost/?code=4%2F0AabcDEF123") == "4/0AabcDEF123")
check("zero-width space stripped",
      go.extract_code("\u200b4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx") ==
      "4/0AX4XfWhAbCdEfGhIjKlMnOpQrStUvWx")
check("empty text -> empty", go.extract_code("") == "")
check("None -> empty", go.extract_code(None) == "")
check("random chatter -> empty", go.extract_code("haan bhai kar do") == "")
check("short junk -> empty", go.extract_code("abc") == "")

# ---------------------------------------------------------------------------
section("2. auth_url asks for offline access + consent")
# ---------------------------------------------------------------------------
_orig_creds = go.client_credentials
go.client_credentials = lambda: ("123-abc.apps.googleusercontent.com", "GOCSPX-secret")
try:
    url = go.auth_url()
finally:
    go.client_credentials = _orig_creds

check("auth_url built", url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"), url)
check("client_id present", "client_id=123-abc.apps.googleusercontent.com" in url)
check("redirect_uri localhost", "redirect_uri=http%3A%2F%2Flocalhost" in url)
check("response_type=code", "response_type=code" in url)
check("gmail scope requested",
      "scope=https%3A%2F%2Fmail.google.com%2F" in url, url)
check("access_type=offline", "access_type=offline" in url)
check("prompt=consent", "prompt=consent" in url)
check("state passed", "state=numerology" in url)

_orig_creds = go.client_credentials
go.client_credentials = lambda: ("", "")
try:
    check("no client -> empty url", go.auth_url() == "")
finally:
    go.client_credentials = _orig_creds

# ---------------------------------------------------------------------------
section("3. XOAUTH2 SASL payload")
# ---------------------------------------------------------------------------
payload = go.xoauth2_string("someone@gmail.com", "ya29.TOKEN")
check("payload starts with user=", payload.startswith("user=someone@gmail.com\x01"))
check("payload carries bearer", "auth=Bearer ya29.TOKEN" in payload)
check("payload ends with double \\x01", payload.endswith("\x01\x01"))
check("payload is a single line", "\n" not in payload)

# ---------------------------------------------------------------------------
section("4. exchange_code never raises")
# ---------------------------------------------------------------------------
_orig_creds = go.client_credentials
go.client_credentials = lambda: ("", "")
try:
    ok, res = go.exchange_code("http://localhost/?code=4/0AabcDEF123")
finally:
    go.client_credentials = _orig_creds
check("missing client -> (False, reason)", ok is False and isinstance(res, str), res)
check("missing client reason mentions client", "client" in res.lower(), res)

_orig_creds = go.client_credentials
go.client_credentials = lambda: ("cid.apps.googleusercontent.com", "GOCSPX-x")
try:
    ok, res = go.exchange_code("kuch bhi nahi")
finally:
    go.client_credentials = _orig_creds
check("no code -> (False, reason)", ok is False and isinstance(res, str), res)
check("no code reason mentions code", "code" in res.lower(), res)

# ---------------------------------------------------------------------------
section("5. friendly error mapping")
# ---------------------------------------------------------------------------
import io
import urllib.error


def _http_error(payload_json):
    body = io.BytesIO(payload_json.encode())
    return urllib.error.HTTPError("https://oauth2.googleapis.com/token", 400,
                                  "Bad Request", {}, body)


msg = go._friendly_error(_http_error('{"error":"invalid_grant"}'))
check("invalid_grant explained", "invalid_grant" in msg and "fresh" in msg.lower(), msg)
msg = go._friendly_error(_http_error('{"error":"redirect_uri_mismatch"}'))
check("redirect_uri_mismatch explained", "Desktop app" in msg, msg)
msg = go._friendly_error(_http_error('{"error":"invalid_client"}'))
check("invalid_client explained", "Client ID" in msg, msg)
msg = go._friendly_error(_http_error('{"error":"unauthorized_client"}'))
check("unauthorized_client explained", "Desktop app" in msg, msg)
msg = go._friendly_error(urllib.error.URLError("no route to host"))
check("network error explained", "Network error" in msg, msg)
msg = go._friendly_error(ValueError("boom"))
check("unknown error stringified", "boom" in msg, msg)

# ---------------------------------------------------------------------------
section("6. status_text reflects the three states")
# ---------------------------------------------------------------------------
_orig = (go.has_client, go.has_refresh_token, go.connected_email)
try:
    go.has_client = lambda: False
    go.has_refresh_token = lambda: False
    check("no client state", "Not set up" in go.status_text(), go.status_text())

    go.has_client = lambda: True
    go.has_refresh_token = lambda: False
    check("pending state", "pending" in go.status_text(), go.status_text())

    go.has_client = lambda: True
    go.has_refresh_token = lambda: True
    go.connected_email = lambda: "someone@gmail.com"
    check("connected state", "someone@gmail.com" in go.status_text(), go.status_text())
finally:
    go.has_client, go.has_refresh_token, go.connected_email = _orig

# ---------------------------------------------------------------------------
section("7. imap_verifier prefers OAuth and reports the method")
# ---------------------------------------------------------------------------
import inspect
from utils import imap_verifier as iv

src = inspect.getsource(iv._open_imap)
check("_open_imap tries OAuth first",
      src.index("_google_oauth_ready") < src.index("password_candidates"), "order wrong")
check("_open_imap has app-password fallback", "password_candidates" in src)
check("oauth-ready helper exists", hasattr(iv, "_google_oauth_ready"))
check("oauth opener exists", hasattr(iv, "_open_imap_oauth"))

sync_src = inspect.getsource(iv._sync_test_connection)
check("test connection reports method", '"method"' in sync_src, sync_src[:200])
check("oauth password is not persisted",
      'used != "XOAUTH2"' in sync_src or "used != 'XOAUTH2'" in sync_src)

accounts_src = inspect.getsource(iv.get_imap_accounts)
check("oauth account listed for scanning", "google_oauth" in accounts_src)
check("oauth account uses XOAUTH2 marker", "XOAUTH2" in accounts_src)

# ---------------------------------------------------------------------------
section("8. admin panel wiring")
# ---------------------------------------------------------------------------
admin_src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "plugins", "admin_actions.py"), encoding="utf-8").read()
check("google_login wizard registered", '"google_login"' in admin_src)
check("google_login callback handled", 'action_data == "google_login"' in admin_src)
check("google login button exists", '"adm_google_login"' in admin_src)
check("google status line in panel", "Google Login:" in admin_src)
check("client id parsed by suffix", ".apps.googleusercontent.com" in admin_src)
check("client secret parsed by prefix", "GOCSPX-" in admin_src)
check("consent link rendered as anchor", "OPEN GOOGLE LOGIN" in admin_src)

# ---------------------------------------------------------------------------
section("9. client credentials can come from environment variables")
# ---------------------------------------------------------------------------
import os as _os

_saved_env = {k: _os.environ.pop(k, None) for k in
              ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")}
_orig_get = go._get
try:
    go._get = lambda key, default="": ""          # nothing stored in the DB
    cid, secret = go.client_credentials()
    check("no env, no db -> built-in default", cid == go.DEFAULT_CLIENT_ID, cid)
    check("built-in secret is a GOCSPX value", secret.startswith("GOCSPX-"), secret)
    check("built-in client id looks like a desktop client",
          cid.endswith(".apps.googleusercontent.com"), cid)
    check("has_client true out of the box", go.has_client() is True)

    _os.environ["GOOGLE_CLIENT_ID"] = "env-123.apps.googleusercontent.com"
    _os.environ["GOOGLE_CLIENT_SECRET"] = "GOCSPX-envsecret"
    cid, secret = go.client_credentials()
    check("env client id used", cid == "env-123.apps.googleusercontent.com", cid)
    check("env client secret used", secret == "GOCSPX-envsecret", secret)
    check("has_client true from env", go.has_client() is True)

    go._get = lambda key, default="": {
        "google_client_id": "db-456.apps.googleusercontent.com",
        "google_client_secret": "GOCSPX-dbsecret",
    }.get(key, "")
    cid, secret = go.client_credentials()
    check("db value wins over env", cid == "db-456.apps.googleusercontent.com", cid)
finally:
    go._get = _orig_get
    for k, v in _saved_env.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v

# ---------------------------------------------------------------------------
section("10. setup text avoids the billing trap")
# ---------------------------------------------------------------------------
check("says it is free", "FREE" in admin_src)
check("says no billing needed", "billing" in admin_src)
check("tells to skip the free-trial page", "Skip" in admin_src or "skip" in admin_src)
check("no Gmail API enable step", "apis/library/gmail.googleapis.com" not in admin_src)
check("consent screen linked", "apis/credentials/consent" in admin_src)
check("test user step present", "Test user" in admin_src)
check("7-day testing warning present", "7 din" in admin_src)
check("publish app step present", "PUBLISH APP" in admin_src)
check("env var shortcut mentioned", "GOOGLE_CLIENT_ID" in admin_src)

# ---------------------------------------------------------------------------
print(f"\n{PASS} passed, {FAIL} failed")
if FAIL:
    print("=== SOME TESTS FAILED ===")
    sys.exit(1)
print("=== ALL TESTS PASSED ===")
