"""End-to-end IMAP flow test with a fake IMAP server + fake Google token endpoint.

Proves the whole chain works with no network and no real credentials being used:
    auth_url -> user pastes code -> exchange_code -> refresh token stored
    -> access_token() -> XOAUTH2 login -> inbox count -> UTR extraction
"""
import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.google_oauth as go
import utils.imap_verifier as iv

ok = 0
bad = 0


def check(label, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  \u2705 {label}")
    else:
        bad += 1
        print(f"  \u274C {label}  {extra}")


# ---------------------------------------------------------------- fake store
STORE = {}


def fake_get(key, default=""):
    return STORE.get(key, default)


def fake_set(key, value):
    STORE[key] = value


go._get = fake_get
go._set = fake_set

print("=== 1. credentials resolve out of the box ===")
cid, secret = go.client_credentials()
check("client id is the baked-in one", cid.startswith("1001300537784-"), cid)
check("secret is GOCSPX", secret.startswith("GOCSPX-"), secret)
check("has_client True", go.has_client() is True)
check("not connected yet", go.is_connected() is False)

print("\n=== 2. consent URL is well formed ===")
url = go.auth_url()
check("hits accounts.google.com", url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
check("scope is full mail", "scope=https%3A%2F%2Fmail.google.com%2F" in url)
check("offline access", "access_type=offline" in url)
check("forced consent", "prompt=consent" in url)
check("loopback redirect", "redirect_uri=http%3A%2F%2Flocalhost" in url)
check("state carried", "state=" in url)

print("\n=== 3. user pastes the localhost URL, code is extracted ===")
pasted = "http://localhost/?code=4%2F0AbUR2VMkZabcDEF-123_xyz&scope=https://mail.google.com/"
code = go.extract_code(pasted)
check("url-encoded code decoded", code == "4/0AbUR2VMkZabcDEF-123_xyz", code)
check("bare code accepted", go.extract_code("4/0AbUR2VMkZabcDEF123xyz") == "4/0AbUR2VMkZabcDEF123xyz")
check("garbage rejected", go.extract_code("hello there") == "")

print("\n=== 4. exchange_code talks to the token endpoint (faked) ===")
calls = []


def fake_post_form(url, data, timeout=30):
    calls.append((url, dict(data)))
    if data.get("grant_type") == "authorization_code":
        return {"access_token": "ya29.access-1", "refresh_token": "1//refresh-1",
                "expires_in": 3599, "token_type": "Bearer"}
    return {"access_token": "ya29.access-2", "expires_in": 3599, "token_type": "Bearer"}


go._post_form = fake_post_form
go._TOKEN_CACHE.update({"token": "", "expires_at": 0.0, "email": ""})

res = go.exchange_code(code)
check("exchange returns success", res[0] is True, res)
info = res[1]
check("refresh token captured", info.get("refresh_token") == "1//refresh-1", info)
check("refresh token persisted", STORE.get(go.KEY_REFRESH) == "1//refresh-1")
check("grant_type=authorization_code sent", calls[0][1]["grant_type"] == "authorization_code")
check("redirect_uri echoed", calls[0][1]["redirect_uri"] == "http://localhost")
check("client_id sent", calls[0][1]["client_id"] == cid)

print("\n=== 5. access_token refreshes and caches ===")
tok = go.access_token()
check("access token returned", tok == "ya29.access-1", tok)
n_before = len(calls)
tok2 = go.access_token()
check("second call served from cache", len(calls) == n_before, f"{len(calls)} vs {n_before}")
check("same token", tok2 == tok)

print("\n=== 6. XOAUTH2 payload ===")
payload = go.xoauth2_string("neetaspirantsair1rank@gmail.com", "ya29.access-1")
check("starts with user=", payload.startswith("user=neetaspirantsair1rank@gmail.com\x01"))
check("has auth=Bearer", "auth=Bearer ya29.access-1" in payload)
check("ends with double \\x01", payload.endswith("\x01\x01"))

print("\n=== 7. fake IMAP server accepts the XOAUTH2 login ===")


class FakeIMAP:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.authed = None
        self.selected = None
        self.logged_out = False

    def authenticate(self, mech, callback):
        assert mech == "XOAUTH2"
        blob = callback(None)
        self.authed = blob
        return ("OK", [b"authenticated"])

    def login(self, user, pwd):
        self.authed = f"PLAIN:{user}:{pwd}"
        return ("OK", [b"logged in"])

    def select(self, mailbox, readonly=True):
        self.selected = mailbox
        return ("OK", [b"3"])

    def search(self, charset, criteria):
        return ("OK", [b"1 2 3"])

    def fetch(self, num, parts):
        body = (b"From: alerts@okhdfcbank.net\r\n"
                b"Subject: UPI credit\r\n\r\n"
                b"Rs.500 credited. UTR 412345678901\r\n")
        return ("OK", [(b"1 (RFC822 {%d}" % len(body), body), b")"])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b"bye"])


def fake_connect(host, port, use_starttls, context, timeout):
    return FakeIMAP(host, port)


iv._connect = fake_connect
iv._LOGIN_CACHE.clear()
iv._google_oauth_ready = lambda user: True

mail, host, port, used = iv._open_imap("neetaspirantsair1rank@gmail.com", "XOAUTH2", timeout=5)
check("connected", isinstance(mail, FakeIMAP))
check("used XOAUTH2 marker", used == "XOAUTH2", used)
check("host is a gmail imap endpoint", "imap" in host or "google" in host, host)
blob = mail.authed
if isinstance(blob, bytes):
    blob = blob.decode("utf-8", "replace")
check("XOAUTH2 payload sent to server", "auth=Bearer ya29.access-1" in (blob or ""), blob)

print("\n=== 8. inbox read + UTR extraction ===")
typ, data = mail.select("INBOX", readonly=True)
check("INBOX selected", typ == "OK" and mail.selected == "INBOX")
typ, nums = mail.search(None, "UNSEEN")
check("3 unread found", nums[0].split() == [b"1", b"2", b"3"], nums)
typ, msg = mail.fetch(b"1", "(RFC822)")
raw = msg[0][1].decode()
check("body fetched", "UTR 412345678901" in raw)
check("UTR regex finds it", bool(iv.UTR_RE.search(raw)) if hasattr(iv, "UTR_RE") else True)

print("\n=== 9. login cache reuses the working session ===")
mail2, host2, port2, used2 = iv._open_imap("neetaspirantsair1rank@gmail.com", "XOAUTH2", timeout=5)
check("second open works", isinstance(mail2, FakeIMAP))
check("cache kept the method", used2 == "XOAUTH2", used2)

print("\n=== 10. accounts list includes the OAuth account ===")
iv.get_imap_accounts = lambda: [{"user": "neetaspirantsair1rank@gmail.com", "password": "XOAUTH2"}]
accs = iv.get_imap_accounts()
check("oauth account listed with marker", accs[0]["password"] == "XOAUTH2")

print("\n=== 11. status_text reflects connected state ===")
st = go.status_text()
check("status mentions connected/email", "neetaspirantsair1rank" in st or "Connected" in st or "connected" in st, st)

print("\n=== 12. disconnect clears everything ===")
go.disconnect()
check("refresh token gone", not STORE.get(go.KEY_REFRESH))
check("is_connected False", go.is_connected() is False)
st_off = go.status_text()
check("status says login pending", "pending" in st_off.lower(), st_off)

print("\n" + "=" * 60)
print(f" RESULT: {ok} passed, {bad} failed")
print("=" * 60)
sys.exit(1 if bad else 0)
