"""Live stock-details card shown *before* any purchase.

Every panel (WhatsApp, TG Number Change, All Apps OTP, panel Telegram accounts,
manually added Basic Telegram accounts) uses the same two-step flow:

    country tap  ->  STOCK DETAILS (live stock + rate + quality notes)  ->  Buy

Nothing is charged on the first tap.  The details card is built here so all
panels look identical and the wording stays honest: the accounts are good
quality / clean numbers, but they are **not** real Premium accounts.
"""
import html

KIND_OTP = "otp"        # virtual number / OTP panels
KIND_TG = "tg"          # panel Telegram accounts (LZT / local stock)
KIND_MANUAL = "manual"  # manually added Basic Telegram accounts

# 2-3 honest quality lines per product kind.
QUALITY_LINES = {
    KIND_OTP: (
        "✅ <b>Quality:</b> fresh, clean virtual number from a good-quality pool",
        "📩 <b>OTP:</b> SMS code is delivered straight into this chat (30–120 sec)",
        "♻️ <b>Refund:</b> if no SMS arrives, cancel and the amount is refunded automatically",
    ),
    KIND_TG: (
        "✅ <b>Quality:</b> good-quality, ready-to-use Telegram account (premium-grade pool)",
        "🔐 <b>Access:</b> session file + phone number, login works on first try",
        "♻️ <b>Support:</b> if the account does not log in, contact support for a replacement",
    ),
    KIND_MANUAL: (
        "✅ <b>Quality:</b> good-quality Basic Telegram account, added manually by the admin",
        "📱 <b>Access:</b> phone number + OTP login, ready to use right away",
        "♻️ <b>Support:</b> any login problem is replaced by the admin",
    ),
}

# The honest disclaimer the owner asked for: premium-looking, but not real premium.
PREMIUM_NOTE = (
    "⚠️ <b>Honest note:</b> these are <b>not</b> real Telegram Premium / "
    "app-Premium accounts. “Premium” here only means <b>good quality, clean "
    "account</b> — you will <b>not</b> get any Premium badge, star or Premium feature."
)


def quality_block(kind=KIND_OTP, extra_lines=()):
    """Return the 2-3 quality lines (plus any extra) as HTML lines."""
    lines = list(QUALITY_LINES.get(kind, QUALITY_LINES[KIND_OTP]))
    lines.extend(extra_lines or ())
    return "\n".join(lines)


def details_message(
    title,
    country_label,
    stock_text,
    rate_text,
    kind=KIND_OTP,
    extra_lines=(),
    extra_block="",
    balance_text=None,
    note=None,
):
    """Build the stock-details card.

    title          -> small header, e.g. "WhatsApp Account — Stock Details"
    country_label  -> already formatted "🇮🇳 India"
    stock_text     -> "12 numbers available" / "Out of stock"
    rate_text      -> "₹25.00 / 0.30 USDT"
    """
    parts = [
        f"<blockquote expandable>📦 <b>{html.escape(str(title))}</b>\n\n",
        f"🌍 <b>Country:</b> {country_label}\n",
        f"📊 <b>Stock:</b> {stock_text}\n",
        f"💵 <b>Rate:</b> {rate_text}\n",
    ]
    if balance_text:
        parts.append(f"👛 <b>Your balance:</b> {balance_text}\n")
    parts.append("\n")
    parts.append(quality_block(kind, extra_lines))
    if extra_block:
        parts.append(f"\n\n{extra_block}")
    parts.append(f"\n\n{note or PREMIUM_NOTE}")
    parts.append("\n\n<i>Tap <b>Buy Now</b> to continue — nothing is charged yet.</i></blockquote>")
    return "".join(parts)


def stock_text(count, unit="numbers"):
    """Human stock label."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "🟡 Live stock unavailable — tap Refresh"
    if count <= 0:
        return "🔴 Out of stock right now"
    if count >= 40:
        return f"🟢 {count}+ {unit} available"
    return f"🟢 {count} {unit} available"
