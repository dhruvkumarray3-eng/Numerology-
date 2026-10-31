"""Shared delivery helper for successful purchase audit messages."""
import html

from config import logger


def _masked_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return f"••••{digits[-4:]}" if digits else "—"


async def notify_purchase_channels(
    client, *, user_id, product, country, phone, price, order_id, provider=None
):
    """Send a successful-purchase record to every configured log channel.

    A channel failure is logged and never reverses an already completed sale.
    The full phone stays in the order database; channel messages show only its
    last four digits to reduce unnecessary exposure.
    """
    try:
        from database import get_log_channels_db
        channels = get_log_channels_db()
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Could not read purchase log channels for order %s: %s", order_id, exc
        )
        return 0

    if not channels:
        logger.warning(
            "Purchase succeeded but no log channels are configured (user=%s, order=%s)",
            user_id,
            order_id,
        )
        return 0

    safe_product = html.escape(str(product or "Unknown product"))
    safe_country = html.escape(str(country or "—"))
    safe_order = html.escape(str(order_id or "—"))
    safe_provider = html.escape(str(provider or "—"))
    message = (
        "<blockquote><b>Purchase completed</b>\n\n"
        f"<b>User:</b> <code>{int(user_id)}</code>\n"
        f"<b>Product:</b> {safe_product}\n"
        f"<b>Country:</b> {safe_country}\n"
        f"<b>Phone:</b> <code>{html.escape(_masked_phone(phone))}</code>\n"
        f"<b>Paid:</b> ₹{float(price):.2f}\n"
        f"<b>Order:</b> <code>{safe_order}</code>\n"
        f"<b>Provider:</b> {safe_provider}</blockquote>"
    )

    if client is None:
        logger.error(
            "Purchase log client unavailable (user=%s, order=%s)", user_id, order_id
        )
        return 0

    delivered = 0
    for channel in channels:
        try:
            await client.send_message(channel, message, parse_mode="html")
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to send purchase log to channel %s for order %s: %s",
                channel,
                order_id,
                exc,
                exc_info=True,
            )
    if not delivered:
        logger.error(
            "Purchase log delivery failed to every configured channel (user=%s, order=%s)",
            user_id,
            order_id,
        )
    return delivered
