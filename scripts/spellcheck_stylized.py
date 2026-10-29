"""Scan the repo for stylized (Unicode math / small-caps / etc.) text and
report words that look misspelled.

Stylized text is invisible to normal grep because it uses codepoints like
U+1D5D4..U+1D607 (mathematical sans bold), U+1D400..U+1D433 (math bold),
small caps, fullwidth, double-struck, script, fraktur, monospace, circled.

This tool parses every Python string literal, folds the stylized characters
back to ASCII, and spell-checks **only the words that actually contained a
stylized character**.  That way code identifiers (``btn_label``) and HTML tags
(``blockquote``) are ignored, and typos like "cdeapest" cannot hide.
"""
import ast
import os
import re
import sys

from spellchecker import SpellChecker

# ---------------------------------------------------------------------------
# Codepoint ranges that map 1:1 onto ASCII letters.
# ---------------------------------------------------------------------------
RANGES = [
    (0x1D400, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # bold
    (0x1D434, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # italic
    (0x1D468, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # bold italic
    (0x1D49C, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # script
    (0x1D4D0, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # bold script
    (0x1D504, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # fraktur
    (0x1D538, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # double-struck
    (0x1D56C, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # bold fraktur
    (0x1D5A0, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # sans-serif
    (0x1D5D4, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # sans bold
    (0x1D608, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # sans italic
    (0x1D63C, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # sans bold italic
    (0x1D670, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),  # monospace
    (0x1D7CE, "0123456789"),
    (0x1D7D8, "0123456789"),
    (0x1D7E2, "0123456789"),
    (0x1D7EC, "0123456789"),
    (0x1D7F6, "0123456789"),
    (0xFF21, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (0xFF41, "abcdefghijklmnopqrstuvwxyz"),
    (0xFF10, "0123456789"),
    (0x24B6, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (0x24D0, "abcdefghijklmnopqrstuvwxyz"),
    (0x1F130, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
]

SMALL_CAPS = {
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ꜰ": "f", "ɢ": "g",
    "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n",
    "ᴏ": "o", "ᴘ": "p", "ǫ": "q", "ʀ": "r", "ꜱ": "s", "ᴛ": "t", "ᴜ": "u",
    "ᴠ": "v", "ᴡ": "w", "ʏ": "y", "ᴢ": "z",
    "ɑ": "a", "ɢ": "g", "ꜰ": "f", "ᴠ": "v",
}

# Letterlike / double-struck capitals that live OUTSIDE the contiguous math ranges
# (e.g. U+2102 BLACK-LETTER CAPITAL C, U+2119 DOUBLE-STRUCK CAPITAL P). Without
# these the folder emits partial words like "rofile" from "ℙ𝕣𝕠𝕗𝕚𝕝𝕖".
EXTRA = {
    0x2102: "C", 0x210D: "H", 0x2115: "N", 0x2119: "P", 0x211A: "Q",
    0x211D: "R", 0x2124: "Z", 0x2130: "E", 0x2131: "F", 0x2133: "M",
    0x1D538: "A", 0x1D539: "B", 0x1D53B: "D", 0x1D53C: "E", 0x1D53D: "F",
    0x1D53E: "G", 0x1D540: "I", 0x1D541: "J", 0x1D542: "K", 0x1D543: "L",
    0x1D544: "M", 0x1D546: "O", 0x1D54A: "S", 0x1D54B: "T", 0x1D54C: "U",
    0x1D54D: "V", 0x1D54E: "W", 0x1D54F: "X", 0x1D550: "Y",
}

FOLD = {}
for start, letters in RANGES:
    for i, ch in enumerate(letters):
        FOLD[start + i] = ch
FOLD.update(SMALL_CAPS)
FOLD.update(EXTRA)


def fold(text):
    return "".join(FOLD.get(ord(c), c) for c in text)


ALLOW = set("""
usdt inr otp smm upi vip bep bnb rdx qr api ids tg pdf lzt imap smtp ok
telegram whatsapp instagram facebook tiktok twitter youtube netflix spotify
gmail google apple paypal binance trustwallet blockchain crypto wallet utr
txn ref referral referrals recharge dashboard panel panels server servers
stock temp mail tempmail session sessions fa sms otps code codes vendor
budget cheapest instant delivery platform platforms category categories
service services order orders balance deposit deposits withdraw withdrawal
bronze silver gold platinum diamond level tier currency language settings
profile stats statistics feedback support owner admin admins superadmin
username userid chat group channel channels join joined verify verification
discount bonus earn earning history logs log purchase purchases buy back
next prev previous cancel confirm close search find filter sort price prices
rate rates amount amounts total spent deposited referred country countries
year years good bad premium basic pro free trial auto manual live offline
online status update updates new old copy copied share link links invite
invites reward rewards points rank ranks badge badges verified unverified
available unavailable instock outofstock success failed error errors warning
info notice account accounts proxy proxies smsactivate fivesim smspva smsman
tempora temporasms fathersmm provider providers gateway payment payments
invoice invoices receipt coupon coupons promo promocode gift gifts spin wheel
lottery contest contests event events news blog faq terms privacy policy
rules guidelines contact email phone number numbers password passwords login
logout signup register registration activate activation deactivate enable
disable enabled disabled on off yes no done pending approved rejected
processing completed cancelled canceled expired valid invalid correct
incorrect wrong right true false null none empty full low high min max
minimum maximum limit limits unlimited daily weekly monthly yearly today
tomorrow yesterday now later soon always never sometimes often once twice
first second third last latest recent popular trending hot top best worst
cheap expensive fast slow quick automatic custom default standard special
exclusive limited extra additional freebie giveaway winner loser lucky
unlucky random select selected choose chosen option options menu menus
button buttons click tap press type send sent receive received reply forward
delete deleted remove removed add added edit edited save saved load loaded
loading refresh reload retry reset restart start stop pause resume play
running stopped paused active inactive open opened closed locked unlocked
secure insecure safe unsafe private public hidden visible shown display
displayed show hide view views preview details detail summary overview
report reports analytics chart charts graph graphs table tables list lists
item items product products catalog catalogs store shop market marketplace
cart checkout billing shipping tracking track package packages bundle
bundles offer offers deal deals sale sales discounts percent percentage tax
taxes fee fees charge charges cost costs profit profits revenue income
expense expenses savings credit debit transfer transfers transaction
transactions refund refunds exchange conversion convert converted value
values unit units quantity qty count counts counter digit digits letter
letters character characters word words line lines page pages file files
folder folders document documents image images photo photos picture
pictures video videos audio music song songs media content contents post
posts comment comments like likes shares follow followers following friend
friends member members user users customer customers client clients buyer
buyers seller sellers vendors supplier suppliers partner partners affiliate
affiliates reseller resellers distributor distributors agent agents manager
managers staff team teams employee employees worker workers developer
developers designer designers creator creators author authors editor editors
moderator moderators owners founder founders ceo cto cfo coo hr pr marketing
seo ads ad advertisement advertisements campaign campaigns promotion
promotions brand brands company companies business businesses organization
organizations agency agencies startup startups enterprise enterprises
corporation corporations limited ltd inc llc plc gmbh sa ag bv nv pty pvt
lookup screenshot acc accs tdata usd apps kripya sirf bejein tnt url bep
""".split())

SPELL = SpellChecker()
SPELL.word_frequency.load_words(ALLOW)


def literals(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def check_text(text):
    """Yield (word, folded_word) for stylized words that look misspelled."""
    # Split into runs, keeping track of which chars were stylized.
    for m in re.finditer(r"[A-Za-z\u0080-\uffff\U0001D400-\U0001D7FF]+", text):
        chunk = m.group(0)
        if not any(ord(c) in FOLD for c in chunk):
            continue
        plain = fold(chunk)
        # Only alphabetic words of 3+ letters.
        for w in re.findall(r"[A-Za-z]{3,}", plain):
            low = w.lower()
            if low in ALLOW or low in SPELL:
                continue
            yield w, low


def main():
    roots = sys.argv[1:] or ["."]
    total = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in {"__pycache__", ".git", "node_modules"}]
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    src = open(path, encoding="utf-8").read()
                    tree = ast.parse(src)
                except Exception as exc:
                    print(f"!! cannot parse {path}: {exc}")
                    continue
                for lineno, value in literals(tree):
                    for word, low in check_text(value):
                        total += 1
                        print(f"{path}:{lineno}: {word!r} -> {low!r}")
    print(f"\n{total} suspicious word(s)")


if __name__ == "__main__":
    main()
