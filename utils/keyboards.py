from telethon import Button
from telethon.tl.types import ReplyKeyboardMarkup, KeyboardButtonRow, KeyboardButton, KeyboardButtonStyle
from config import TERMS_URL, PRIVACY_URL, JOIN_URLS, USE_PREMIUM_EMOJIS
from database import is_admin, get_support_url, get_fsub_urls

# Owner-supplied premium emoji id used on EVERY Search button in the bot.
# Import this constant instead of hard-coding the id so a single change
# updates every search button at once.
SEARCH_EMOJI_ID = 5229102316145106683

# ---------------------------------------------------------------------------
# Premium (custom) emoji support
#
# Two different mechanisms exist in Telegram and they are NOT interchangeable:
#
#   * Message text  -> ``<tg-emoji emoji-id="123">⚡</tg-emoji>`` inside HTML.
#                      Telethon parses this into ``MessageEntityCustomEmoji``.
#   * Button label  -> the ``icon`` field of ``KeyboardButtonStyle``.  You must
#                      pass the numeric emoji id; HTML tags are *not* parsed in
#                      button text.
#
# Telegram only renders custom emoji sent by a bot when the bot's owner has an
# active Telegram Premium subscription, or when the bot owns an additional
# username purchased on Fragment.  When that is not the case Telegram silently
# falls back to the plain emoji, so passing an icon is always safe.
# ---------------------------------------------------------------------------

# Semantic name -> verified custom emoji id.  Reused across the whole bot so
# every panel can simply say ``icon="buy"`` instead of memorising raw ids.
PREMIUM_ICONS = {
    "buy": 5440627033111557670,
    "cart": 5440627033111557670,
    "deposit": 5409271925014801629,
    "money": 5409320020058584473,
    "balance": 5409320020058584473,
    "profile": 6203982793379154737,
    "user": 6203982793379154737,
    "users": 6203982793379154737,
    "orders": 5409098988156629257,
    "order": 5409098988156629257,
    "check": 5409098988156629257,
    "stock": 6129627894349045589,
    "chart": 6129627894349045589,
    "stats": 6129627894349045589,
    "refer": 5354889508674360491,
    "gift": 5440627033111557670,
    "support": 6129732880529628243,
    "help": 6129732880529628243,
    "doc": 6129732880529628243,
    "code": 6129732880529628243,
    "home": 6129399728506412489,
    "close": 6129812419028982717,
    "back": 6129812419028982717,
    "crown": 5409166771330494453,
    "admin": 5409166771330494453,
    "panel": 5409166771330494453,
    "lock": 5409166771330494453,
    "lightning": 5409271925014801629,
    "star": 5409320020058584473,
    "refresh": 5409320020058584473,
    "fire": 5409320020058584473,
    "settings": 5409098988156629257,
    "key": 5409098988156629257,
    "delete": 5408832111773757273,
    "warning": 5408832111773757273,
    "cleanup": 5408832111773757273,
    "phone": 5409119256107297715,
    "globe": 5409119256107297715,
    "apps": 5409119256107297715,
    "zip": 5355292788923593967,
    "telegram": 5330237710655306682,
    "telegram_basic": 5330237710655306682,
    "numchange": 5330237710655306682,
    "number_change": 5330237710655306682,
    "instagram": 5409271925014801629,
    "whatsapp": 5334998226636390258,
    "youtube": 5409320020058584473,
    "facebook": 6154249597532248059,
    "tiktok": 6203982793379154737,
    "twitter": 6129732880529628243,
    # --- owner-supplied premium emoji ids ---
    "premium": 5796209712009581332,
    "allapps": 5373130604147654226,
    "allapps_otp": 5373130604147654226,
    "otp": 5373130604147654226,
    "server": 5981035310241288157,
    "servers": 5981035310241288157,
    "source": 5951663025336356427,
    "source_codes": 5951663025336356427,
    "src": 5951663025336356427,
    # Owner-supplied premium emoji used on every Search button.
    "search": 5229102316145106683,
    "find": 5229102316145106683,
    "more": 5289947142142577318,
    "more_content": 5289947142142577318,
    "content": 5289947142142577318,
}


def resolve_icon(icon):
    """Turn a semantic name / numeric string / int into a custom emoji id.

    Returns ``None`` when premium emojis are disabled or the value is unknown,
    which makes Telegram render the button exactly like a normal one.
    """
    if icon is None or not USE_PREMIUM_EMOJIS:
        return None
    if isinstance(icon, bool):
        return None
    if isinstance(icon, int):
        return icon
    if isinstance(icon, str):
        value = icon.strip()
        if value.isdigit():
            return int(value)
        return PREMIUM_ICONS.get(value.lower())
    return None


def pe(name, fallback="✨"):
    """Return an HTML ``<tg-emoji>`` snippet for message text.

    ``name`` may be a semantic key (``"crown"``) or a raw emoji id.
    Falls back to the plain emoji when premium emojis are disabled.
    """
    if not USE_PREMIUM_EMOJIS:
        return fallback
    if isinstance(name, int):
        eid = name
    elif isinstance(name, str):
        value = name.strip()
        eid = int(value) if value.isdigit() else PREMIUM_ICONS.get(value.lower())
    else:
        eid = None
    if not eid:
        return fallback
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'


# We use bg_primary (blue), bg_success (green), bg_danger (red)
# For icon, we pass the custom emoji ID (int) or a semantic name.

def _parse_style_icon(args, style_type, icon):
    """Normalise ``style_type``/``icon`` from any calling convention.

    Style names are always strings (``"primary"``/``"success"``/``"danger"``)
    while premium emoji ids are always integers.  Accepting ``*args`` lets us
    survive the classic mistake of passing the emoji id positionally *and*
    ``icon=`` as a keyword, which would otherwise raise
    ``TypeError: style_btn() got multiple values for argument 'icon'`` before
    the function body even runs.
    """
    if args:
        first = args[0]
        if isinstance(first, int):
            if icon is None:
                icon = first
        else:
            if style_type is None:
                style_type = first
            if len(args) > 1 and icon is None and isinstance(args[1], int):
                icon = args[1]
    return style_type, icon


def style_btn(text, data, *args, style_type=None, icon=None, **kwargs):
    style_type, icon = _parse_style_icon(args, style_type, icon)
    return Button.inline(text, data, style=style_type, icon=resolve_icon(icon))

def style_url(text, url, *args, style_type=None, icon=None, **kwargs):
    style_type, icon = _parse_style_icon(args, style_type, icon)
    return Button.url(text, url, style=style_type, icon=resolve_icon(icon))


def get_terms_buttons():
    return [
        [style_btn("𝐀ᴄᴄᴇᴘᴛ", b"tc_accept", style_type='success', icon=5409380965644514142),
         style_btn("𝐑ᴇᴊᴇᴄᴛ", b"tc_reject", style_type='danger', icon=5354889508674360491)]
    ]
def get_join_buttons():
    urls = get_fsub_urls()
    buttons = [[style_url(f"📢 Join Channel {i+1}", link, "primary", icon=5409119256107297715)] for i, link in enumerate(urls) if link]
    buttons.append([style_btn("𝐕ᴇʀɪғʏ 𝐉ᴏɪɴᴇᴅ", b"verify_join", style_type='success', icon=6129627894349045589)])
    return buttons

def get_persistent_menu(uid):
    """Bottom reply keyboard.

    Deliberately *not* marked ``persistent``: a persistent keyboard can never
    be hidden by the user, but this menu has to stay collapsible so it can be
    tucked away while typing (Telegram's own keyboard toggle reopens it).
    ``resize`` keeps it compact instead of full keyboard height.
    """
    from database import is_admin
    from telethon import Button
    buttons = [
        [Button.text("🛒 𝐁ᴜʏ 𝐀ᴄᴄᴏᴜɴᴛ", resize=True, style="success", icon=5841670626577748398), Button.text("💳 𝐃ᴇᴘᴏsɪᴛ", style="primary", icon=5409271925014801629)],
        [Button.text("👤 𝐏ʀᴏғɪʟᴇ", style="primary", icon=6203982793379154737), Button.text("📦 𝐌ʏ 𝐎ʀᴅᴇʀs", style="primary", icon=5409098988156629257)],
        [Button.text("💰 𝐁ᴀʟᴀɴᴄᴇ", style="success", icon=5409320020058584473), Button.text("📊 𝐒ᴛᴏᴄᴋ", style="primary", icon=6129627894349045589)],
        [Button.text("🎁 𝐑ᴇғᴇʀ", style="success", icon=5354889508674360491), Button.text("📩 𝐒ᴜᴘᴘᴏʀᴛ", style="primary", icon=6129732880529628243)],
        [Button.text("🏠 𝐒ᴛᴀʀᴛ", style="success", icon=6129399728506412489), Button.text("🔻 𝐂ʟᴏsᴇ", style="danger", icon=6129812419028982717)]
    ]
    buttons.append([Button.text("🆘 Help", style="primary", icon=6129732880529628243)])
    if is_admin(uid):
        buttons.append([Button.text("🔐 𝐀ᴅᴍɪɴ 𝐏ᴀɴᴇʟ", style="danger", icon=5409166771330494453)])
    return buttons

def get_support_buttons():
    urls = get_fsub_urls()
    sup_url = get_support_url()
    t_url = TERMS_URL if (TERMS_URL and str(TERMS_URL).strip().startswith("http")) else sup_url
    p_url = PRIVACY_URL if (PRIVACY_URL and str(PRIVACY_URL).strip().startswith("http")) else None
    buttons = [
        [style_url("📩 Support", sup_url, "success", icon=6129732880529628243)],
        [style_url("📜 Terms & Conditions", t_url, "primary", icon=6129732880529628243)]
    ]
    if p_url:
        buttons.append([style_url("🔒 Privacy Policy", p_url, "danger", icon=5409166771330494453)])
    if urls:
        buttons.append([style_url("📢 Channel", urls[0], "primary", icon=5409119256107297715)])
    return buttons

# ---------------------------------------------------------------------------
# Stylised-text matching
#
# The reply keyboard uses "fancy" Unicode glyphs (mathematical bold capitals
# plus Latin small-capital letters) so the menu looks premium, e.g.
#   "🛒 𝗕ᴜʏ 𝗔ᴄᴄᴏᴜɴᴛ"  instead of  "🛒 Buy Account"
# Telegram sends back the *rendered* label, so plain ASCII regexes never
# match.  `normalise_menu_text()` folds every such glyph back to ASCII so a
# handler can reliably detect which button was tapped.
# ---------------------------------------------------------------------------
_MENU_FOLD = {}


def _build_menu_fold():
    # Mathematical bold / italic / script / fraktur / double-struck / sans
    # and monospace letter ranges all sit in contiguous 26-letter blocks.
    blocks = [
        0x1D400, 0x1D434, 0x1D468, 0x1D49C, 0x1D4D0, 0x1D504, 0x1D538,
        0x1D56C, 0x1D5A0, 0x1D5D4, 0x1D608, 0x1D63C, 0x1D670,
    ]
    for base in blocks:
        for i in range(26):
            _MENU_FOLD[chr(base + i)] = chr(ord("A") + i)
            _MENU_FOLD[chr(base + 26 + i)] = chr(ord("a") + i)
    # Latin small capitals and common look-alikes used in the menu.
    small_caps = {
        "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ꜰ": "f",
        "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k", "ʟ": "l",
        "ᴍ": "m", "ɴ": "n", "ᴏ": "o", "ᴘ": "p", "ǫ": "q", "ʀ": "r",
        "ꜱ": "s", "ᴛ": "t", "ᴜ": "u", "ᴠ": "v", "ᴡ": "w", "ʏ": "y",
        "ᴢ": "z", "ꜱ": "s", "ꜰ": "f", "ᴠ": "v", "ᴢ": "z",
        "ᵢ": "i", "ᵣ": "r", "ᵤ": "u", "ᵥ": "v",
        "ꜱ": "s", "ᴏ": "o", "ᴇ": "e", "ᴅ": "d", "ᴄ": "c",
    }
    _MENU_FOLD.update(small_caps)
    # Cyrillic / IPA look-alikes that appear in some labels.
    _MENU_FOLD.update({
        "ӏ": "l", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w",
        "\u0493": "f",  # Cyrillic ghe with stroke, used for "f"
        "\u0274": "n",  # Latin small capital N
        "\u0280": "r",  # Latin small capital R
        "\u0299": "b",  # Latin small capital B
        "\u1d1c": "u",  # Latin small capital U
        "\u028f": "y",  # Latin small capital Y
        "\u026a": "i",  # Latin small capital I
        "\u029f": "l",  # Latin small capital L
    })


_build_menu_fold()


def normalise_menu_text(value) -> str:
    """Fold stylised Unicode letters to plain ASCII and strip decoration."""
    text = str(value or "")
    folded = "".join(_MENU_FOLD.get(ch, ch) for ch in text)
    return "".join(ch for ch in folded.lower() if ch.isalnum())


def matches_menu(value, *keys) -> bool:
    """True when `value` (a button label) contains any of the given keys."""
    norm = normalise_menu_text(value)
    return any(normalise_menu_text(k) in norm for k in keys)


# ---------------------------------------------------------------------------
# Canonical reply-keyboard label registry
#
# Every bottom keyboard button is declared here exactly once.  Handlers match
# against the *canonical key* instead of re-typing the stylised glyphs, which
# is what previously broke the Stock and Profile buttons: the regex in the
# handler used a different Unicode block (double-struck "𝕊"/"ℙ") than the
# keyboard actually sends (mathematical bold "𝐒"/"𝐏").
# ---------------------------------------------------------------------------
_MENU_LABEL_KEYS = {
    "buyaccount": "buy_account",
    "deposit": "deposit",
    "profile": "profile",
    "mystats": "my_stats",
    "myorders": "my_orders",
    "balance": "balance",
    "stock": "stock",
    "refer": "refer",
    "referearn": "refer",
    "support": "support",
    "start": "start",
    "menu": "start",
    "close": "close",
    "hide": "close",
    "help": "help",
    "helpcommands": "help",
    "adminpanel": "admin_panel",
    "settings": "settings",
    "servers": "servers",
    "freetempmail": "tempmail",
    "recharge": "recharge",
}


def menu_label_key(value):
    """Return the canonical key for a reply-keyboard label, or ``None``.

    Matching is *exact* after folding (emoji and punctuation are stripped), so
    a genuine country query such as ``"Stockholm"`` is never mistaken for the
    ``Stock`` button.
    """
    return _MENU_LABEL_KEYS.get(normalise_menu_text(value))


def is_menu_label(value) -> bool:
    """True when ``value`` is one of the known reply-keyboard labels."""
    return menu_label_key(value) is not None
