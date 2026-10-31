"""Manual "Basic Telegram Account" stock.

This is a completely separate stock pool from the Telethon-session `stock`
table.  An admin adds ready-made Telegram accounts by hand (country, phone,
optional session string, optional 2FA password and a price) and users buy
them straight from a dedicated panel.

Keeping it separate means:
  * old/stale auto-imported stock can be wiped without touching manual stock;
  * manual accounts never need a live Telethon session scan to be sold;
  * pricing is fully controlled by the admin.
"""

from __future__ import annotations

import time

from database import db, cur

_TABLE_READY = False


def ensure_manual_table() -> None:
    """Create the manual_accounts table (idempotent)."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS manual_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT NOT NULL,
            phone TEXT NOT NULL,
            session TEXT,
            twofa TEXT,
            price REAL NOT NULL DEFAULT 0,
            note TEXT,
            available INTEGER NOT NULL DEFAULT 1,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sold_to INTEGER,
            sold_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_manual_country
            ON manual_accounts (country, available);
        """
    )
    db.commit()
    _TABLE_READY = True


# --------------------------------------------------------------------------
# Admin helpers
# --------------------------------------------------------------------------
def add_manual_account(country, phone, session="", twofa="", price=0.0,
                       note="", added_by=0):
    """Insert one manual account and return its id."""
    ensure_manual_table()
    country = (country or "").strip()
    phone = str(phone or "").strip().lstrip("+")
    if not country or not phone:
        raise ValueError("country and phone are required")
    cur.execute(
        "INSERT INTO manual_accounts "
        "(country, phone, session, twofa, price, note, available, added_by) "
        "VALUES (?,?,?,?,?,?,1,?)",
        (country, phone, (session or "").strip(), (twofa or "").strip(),
         float(price or 0), (note or "").strip(), added_by),
    )
    db.commit()
    return cur.lastrowid


def list_manual_accounts(available_only=False, country=None, limit=200):
    """Return manual account rows as dicts (newest first)."""
    ensure_manual_table()
    sql = "SELECT id, country, phone, session, twofa, price, note, available, " \
          "added_by, added_at, sold_to, sold_at FROM manual_accounts"
    clauses, params = [], []
    if available_only:
        clauses.append("available=1")
    if country:
        clauses.append("LOWER(country)=LOWER(?)")
        params.append(country)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = cur.execute(sql, params).fetchall()
    keys = ("id", "country", "phone", "session", "twofa", "price", "note",
            "available", "added_by", "added_at", "sold_to", "sold_at")
    return [dict(zip(keys, r)) for r in rows]


def manual_countries():
    """Return [(country, available_count, min_price)] sorted by count desc."""
    ensure_manual_table()
    rows = cur.execute(
        "SELECT country, COUNT(*), MIN(price) FROM manual_accounts "
        "WHERE available=1 GROUP BY country ORDER BY COUNT(*) DESC, country ASC"
    ).fetchall()
    return [(r[0], int(r[1] or 0), float(r[2] or 0)) for r in rows]


def manual_count(country=None):
    ensure_manual_table()
    if country:
        row = cur.execute(
            "SELECT COUNT(*) FROM manual_accounts WHERE available=1 AND LOWER(country)=LOWER(?)",
            (country,),
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT COUNT(*) FROM manual_accounts WHERE available=1"
        ).fetchone()
    return int(row[0] or 0) if row else 0


def get_manual_account(account_id):
    ensure_manual_table()
    row = cur.execute(
        "SELECT id, country, phone, session, twofa, price, note, available, "
        "added_by, added_at, sold_to, sold_at FROM manual_accounts WHERE id=?",
        (account_id,),
    ).fetchone()
    if not row:
        return None
    keys = ("id", "country", "phone", "session", "twofa", "price", "note",
            "available", "added_by", "added_at", "sold_to", "sold_at")
    return dict(zip(keys, row))


def delete_manual_account(account_id):
    ensure_manual_table()
    cur.execute("DELETE FROM manual_accounts WHERE id=?", (account_id,))
    db.commit()
    return cur.rowcount


def clear_manual_accounts(country=None):
    """Delete manual accounts (all, or one country). Returns rows removed."""
    ensure_manual_table()
    if country:
        cur.execute("DELETE FROM manual_accounts WHERE LOWER(country)=LOWER(?)", (country,))
    else:
        cur.execute("DELETE FROM manual_accounts")
    db.commit()
    return cur.rowcount


# --------------------------------------------------------------------------
# Purchase (atomic)
# --------------------------------------------------------------------------
def purchase_manual_account(uid, account_id):
    """Atomically sell an available manual account to `uid`.

    Returns a dict:
        {"ok": True, "account": {...}}
        {"ok": False, "error": "not_found" | "insufficient" | "race"}
    Balance is deducted only when the row is successfully marked sold.
    """
    ensure_manual_table()
    acct = get_manual_account(account_id)
    if not acct or not acct.get("available"):
        return {"ok": False, "error": "not_found"}

    price = float(acct.get("price") or 0)
    try:
        bal_row = db.execute(
            "SELECT balance FROM users WHERE user_id=?", (uid,)
        ).fetchone()
        balance = float(bal_row[0]) if bal_row and bal_row[0] is not None else 0.0
        if balance < price:
            return {"ok": False, "error": "insufficient", "balance": balance,
                    "price": price}

        # Guard against a double-tap: only one UPDATE can flip available 1->0.
        updated = db.execute(
            "UPDATE manual_accounts SET available=0, sold_to=?, sold_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND available=1",
            (uid, account_id),
        )
        if updated.rowcount != 1:
            db.rollback()
            return {"ok": False, "error": "race"}

        charged = db.execute(
            "UPDATE users SET balance = balance - ? "
            "WHERE user_id=? AND balance >= ?",
            (price, uid, price),
        )
        if charged.rowcount != 1:
            db.rollback()
            latest = db.execute(
                "SELECT balance FROM users WHERE user_id=?", (uid,)
            ).fetchone()
            current_balance = float(latest[0]) if latest and latest[0] is not None else 0.0
            return {"ok": False, "error": "insufficient", "balance": current_balance,
                    "price": price}
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        return {"ok": False, "error": "db", "detail": str(exc)}

    acct["available"] = 0
    acct["sold_to"] = uid
    acct["sold_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return {"ok": True, "account": acct}


def manual_stats():
    """Quick admin summary: available / sold / revenue."""
    ensure_manual_table()
    avail = cur.execute("SELECT COUNT(*) FROM manual_accounts WHERE available=1").fetchone()[0]
    sold = cur.execute("SELECT COUNT(*) FROM manual_accounts WHERE available=0").fetchone()[0]
    rev = cur.execute(
        "SELECT COALESCE(SUM(price),0) FROM manual_accounts WHERE available=0"
    ).fetchone()[0]
    return {"available": int(avail or 0), "sold": int(sold or 0),
            "revenue": float(rev or 0)}
