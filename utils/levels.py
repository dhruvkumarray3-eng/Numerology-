"""Live VIP level system driven by BOTH deposits and spending.

The old dashboard picked a tier from the user's *current balance* only, which
meant a user who deposited a lot but then spent it all silently dropped back to
Bronze.  This module instead computes a **loyalty score** from the user's
lifetime activity:

    score = total_deposited + total_spent

Both depositing money *and* buying accounts push the score up, so the tier
reflects how much a customer has actually done with the bot.  Everything is
recomputed on every render (``compute_level`` is called fresh each time the
dashboard or stats screen is built), so the level is always live.

The module is deliberately dependency-light and never raises: any database
error degrades to a zero score instead of crashing a handler.
"""

from __future__ import annotations

# Ordered from lowest to highest.  ``min_score`` is the loyalty score required
# to *reach* that tier.  Keep the emojis in sync with the dashboard styling.
TIERS = [
    {"key": "bronze", "name": "Bronze", "emoji": "🏆", "min_score": 0},
    {"key": "silver", "name": "Silver", "emoji": "🥈", "min_score": 500},
    {"key": "gold", "name": "Gold", "emoji": "🥇", "min_score": 2000},
    {"key": "platinum", "name": "Platinum", "emoji": "💠", "min_score": 5000},
    {"key": "diamond", "name": "Diamond", "emoji": "💎", "min_score": 10000},
]


def get_user_totals(uid):
    """Return ``(total_deposited, total_spent)`` for a user, in INR.

    ``total_deposited`` comes from the users table; ``total_spent`` is the sum
    of every order price.  Any failure returns zeros so callers stay safe.
    """
    deposited = 0.0
    spent = 0.0
    try:
        from database import cur
        row = cur.execute(
            "SELECT total_deposited FROM users WHERE user_id=?", (uid,)
        ).fetchone()
        if row and row[0] is not None:
            deposited = float(row[0])
        o_row = cur.execute(
            "SELECT COALESCE(SUM(price), 0) FROM orders WHERE user_id=?", (uid,)
        ).fetchone()
        if o_row and o_row[0] is not None:
            spent = float(o_row[0])
    except Exception:
        pass
    return deposited, spent


def loyalty_score(deposited, spent):
    """Combine deposits and spending into a single comparable score."""
    try:
        return max(0.0, float(deposited)) + max(0.0, float(spent))
    except (TypeError, ValueError):
        return 0.0


def tier_for_score(score):
    """Return the highest tier whose ``min_score`` the score satisfies."""
    current = TIERS[0]
    for tier in TIERS:
        if score >= tier["min_score"]:
            current = tier
        else:
            break
    return current


def compute_level(uid):
    """Full live level snapshot for ``uid``.

    Returns a dict::

        {
            "deposited": float,      # lifetime deposits (INR)
            "spent": float,          # lifetime spend (INR)
            "score": float,          # deposited + spent
            "tier": {...},           # current tier dict
            "next_tier": {...} | None,
            "need": float,           # score still required for next tier
            "progress": float,       # 0..100 progress toward next tier
            "is_max": bool,
        }
    """
    deposited, spent = get_user_totals(uid)
    score = loyalty_score(deposited, spent)
    tier = tier_for_score(score)

    idx = TIERS.index(tier)
    next_tier = TIERS[idx + 1] if idx + 1 < len(TIERS) else None

    if next_tier is None:
        need = 0.0
        progress = 100.0
    else:
        span = max(1.0, next_tier["min_score"] - tier["min_score"])
        done = max(0.0, score - tier["min_score"])
        progress = min(100.0, (done / span) * 100.0)
        need = max(0.0, next_tier["min_score"] - score)

    return {
        "deposited": deposited,
        "spent": spent,
        "score": score,
        "tier": tier,
        "next_tier": next_tier,
        "need": need,
        "progress": progress,
        "is_max": next_tier is None,
    }


def tier_label(tier):
    """Return ``"🏆 Bronze"`` style label for a tier dict."""
    if not tier:
        return ""
    return f"{tier.get('emoji', '')} {tier.get('name', '')}".strip()
