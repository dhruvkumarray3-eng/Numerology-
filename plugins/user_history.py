"""Admin-facing **User History** console.

Type a user id (or tap a user from any admin screen) and instantly get the
complete picture of that account:

  * profile card      - balance, deposits, spend, profit, discount, tier, ban
  * deposits          - every recharge with method, amount, status and date
  * purchases         - stock orders, panel orders (WhatsApp / Number Change /
                        All Apps OTP / LZT) and SMM orders
  * wallet            - redeem codes, auto-UPI credits, refunds
  * timeline          - every single action merged into one chronological feed

Everything is rendered with premium emojis and colour-coded buttons.
"""
import html
from datetime import datetime, timezone

from telethon import events

from config import logger
from database import cur, db, is_admin, has_perm
from utils.keyboards import style_btn, pe

# Pre-computed premium-emoji snippets (f-strings cannot contain backslashes
# in their expression part on Python 3.11, so we resolve them once here).
PE_USER = pe("user", "\U0001F464")
PE_MONEY = pe("money", "\U0001F4B0")
PE_DEPOSIT = pe("deposit", "\U0001F4B3")
PE_CART = pe("cart", "\U0001F6D2")
PE_CHART = pe("chart", "\U0001F4C8")
PE_GIFT = pe("gift", "\U0001F381")
PE_STAR = pe("star", "\u2B50")
PE_CHECK = pe("check", "\u2705")
PE_DOC = pe("doc", "\U0001F4C5")
PE_REFER = pe("refer", "\U0001F91D")
PE_STATS = pe("stats", "\U0001F4CA")
PE_WARNING = pe("warning", "\u26A0\uFE0F")
PE_SEARCH = pe("search", "\U0001F50D")

# ---------------------------------------------------------------------------
# state: admin uid -> True while we are waiting for a user id
# ---------------------------------------------------------------------------
uh_state = {}

PAGE_SIZE = 6

TABS = (
    ("overview", "Overview", "profile", "\U0001F464", "primary"),
    ("deposits", "Deposits", "deposit", "\U0001F4B3", "success"),
    ("purchases", "Purchases", "cart", "\U0001F6D2", "primary"),
    ("wallet", "Wallet", "money", "\U0001F4B0", "success"),
    ("timeline", "Timeline", "chart", "\U0001F4C8", "primary"),
)
TAB_KEYS = tuple(t[0] for t in TABS)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _q(sql, params=()):
    """Run a query and never raise - a missing table just yields no rows."""
    try:
        return cur.execute(sql, params).fetchall()
    except Exception:
        return []


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _inr(value):
    """Format an INR amount the way the rest of the bot does."""
    try:
        from utils.markup import format_inr
        return format_inr(_num(value))
    except Exception:
        return f"\u20b9{_num(value):,.2f}"


def _usdt(value_inr):
    try:
        from utils.markup import get_usdt_rate
        rate = float(get_usdt_rate() or 0)
        if rate <= 0:
            return ""
        return f"{_num(value_inr) / rate:,.2f} USDT"
    except Exception:
        return ""


def _dual(value_inr):
    usdt = _usdt(value_inr)
    return f"{_inr(value_inr)} \u00b7 {usdt}" if usdt else _inr(value_inr)


def _fmt_date(raw):
    """Best-effort human date from whatever the DB stored."""
    if raw in (None, "", 0):
        return "\u2014"
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).strftime("%d %b %Y, %H:%M")
        except Exception:
            return str(raw)
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d %b %Y, %H:%M")
        except ValueError:
            continue
    return text[:32]


def _ts(raw):
    """Best-effort sortable timestamp from whatever the DB stored."""
    if raw in (None, "", 0):
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def _short(text, limit=34):
    text = str(text or "\u2014")
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _status_badge(status):
    s = str(status or "").lower()
    if s in ("success", "completed", "complete", "paid", "delivered", "done"):
        return "\u2705 " + s.title()
    if s in ("pending", "processing", "in_progress", "waiting"):
        return "\u23f3 " + s.replace("_", " ").title()
    if s in ("cancel", "cancelled", "canceled", "failed", "refunded", "expired"):
        return "\u274c " + s.replace("_", " ").title()
    return "\u2022 " + (s.title() if s else "Unknown")


def _tier(total_deposited):
    tiers = (("Bronze", 0), ("Silver", 500), ("Gold", 2000),
             ("Platinum", 5000), ("Diamond", 15000))
    current, nxt = tiers[0][0], None
    for i, (name, floor) in enumerate(tiers):
        if total_deposited >= floor:
            current = name
            nxt = tiers[i + 1] if i + 1 < len(tiers) else None
    if not nxt:
        return current, 0
    return current, max(nxt[1] - total_deposited, 0)


# ---------------------------------------------------------------------------
# data collection
# ---------------------------------------------------------------------------
def collect_user_history(uid):
    """Return a dict with everything we know about ``uid``."""
    data = {"uid": uid, "exists": False}

    rows = _q("SELECT balance, total_deposited, joined_date, banned, discount, "
              "referred_by, terms_accepted FROM users WHERE user_id=?", (uid,))
    if rows:
        r = rows[0]
        data.update({
            "exists": True,
            "balance": _num(r[0]),
            "total_deposited": _num(r[1]),
            "joined": r[2],
            "banned": bool(r[3]),
            "discount": _num(r[4]),
            "referred_by": r[5],
            "terms": bool(r[6]) if len(r) > 6 else False,
        })
    else:
        data.update({"balance": 0.0, "total_deposited": 0.0, "joined": None,
                     "banned": False, "discount": 0.0, "referred_by": None,
                     "terms": False})

    # ---- deposits (manual + auto UPI) ---------------------------------
    deposits = []
    for row in _q("SELECT id, amount, method_name, status, date FROM deposits "
                  "WHERE user_id=? ORDER BY id DESC", (uid,)):
        deposits.append({
            "kind": "Deposit",
            "icon": "\U0001F4B3",
            "label": str(row[2] or "Deposit"),
            "amount": _num(row[1]),
            "status": row[3],
            "date": row[4],
            "ref": row[0],
        })
    for row in _q("SELECT order_id, amount, status, date FROM upi_orders "
                  "WHERE user_id=? ORDER BY rowid DESC", (uid,)):
        deposits.append({
            "kind": "UPI Deposit",
            "icon": "\U0001F3E6",
            "label": f"Auto-UPI {row[0]}",
            "amount": _num(row[1]),
            "status": row[2],
            "date": row[3],
            "ref": row[0],
        })
    for row in _q("SELECT utr, amount, date FROM redeemed_transactions "
                  "WHERE user_id=? ORDER BY rowid DESC", (uid,)):
        deposits.append({
            "kind": "Auto UPI",
            "icon": "\u26A1",
            "label": f"UTR {row[0]}",
            "amount": _num(row[1]),
            "status": "success",
            "date": row[2],
            "ref": row[0],
        })
    data["deposits"] = deposits
    data["deposit_total"] = sum(d["amount"] for d in deposits
                                if str(d["status"]).lower() in
                                ("success", "completed", "paid", "complete", ""))
    data["deposit_count"] = len(deposits)

    # ---- stock orders --------------------------------------------------
    purchases = []
    for row in _q("SELECT id, country, year, price, phone, date FROM orders "
                  "WHERE user_id=? ORDER BY id DESC", (uid,)):
        purchases.append({
            "kind": "Account",
            "icon": "\U0001F4F1",
            "label": f"{row[1] or 'Account'} \u00b7 {row[2] or ''}".strip(),
            "detail": f"+{row[4]}" if row[4] else "",
            "amount": _num(row[3]),
            "status": "success",
            "date": row[5],
            "ref": row[0],
        })

    # ---- panel orders (WhatsApp / NumChange / All Apps / LZT) ----------
    panel_profit = 0.0
    for row in _q("SELECT id, panel, country, price, real_price, profit, status, date "
                  "FROM panel_orders WHERE user_id=? ORDER BY id DESC", (uid,)):
        panel_profit += _num(row[5])
        purchases.append({
            "kind": "Panel",
            "icon": "\U0001F9E9",
            "label": f"{row[1] or 'Panel'} \u00b7 {row[2] or ''}".strip(" \u00b7"),
            "detail": "",
            "amount": _num(row[3]),
            "cost": _num(row[4]),
            "profit": _num(row[5]),
            "status": row[6],
            "date": row[7],
            "ref": row[0],
        })

    # ---- SMM orders ----------------------------------------------------
    for row in _q("SELECT id, service_name, quantity, price, status, date "
                  "FROM smm_orders WHERE user_id=? ORDER BY id DESC", (uid,)):
        purchases.append({
            "kind": "SMM",
            "icon": "\U0001F680",
            "label": f"{_short(row[1], 26)} \u00d7 {row[2] or 0}",
            "detail": "",
            "amount": _num(row[3]),
            "status": row[4],
            "date": row[5],
            "ref": row[0],
        })

    # ---- manual accounts bought ---------------------------------------
    for row in _q("SELECT id, country, phone, price, sold_at FROM manual_accounts "
                  "WHERE sold_to=? ORDER BY id DESC", (uid,)):
        purchases.append({
            "kind": "Manual",
            "icon": "\U0001F511",
            "label": f"{row[1] or 'Manual'} \u00b7 +{row[2] or ''}".strip(" \u00b7"),
            "detail": "",
            "amount": _num(row[3]),
            "status": "success",
            "date": row[4],
            "ref": row[0],
        })

    data["purchases"] = purchases
    data["purchase_total"] = sum(p["amount"] for p in purchases)
    data["purchase_count"] = len(purchases)
    data["profit_total"] = panel_profit

    # ---- wallet: redeem codes ------------------------------------------
    wallet = []
    for row in _q("SELECT id, code, amount, date FROM redeem_log "
                  "WHERE user_id=? ORDER BY id DESC", (uid,)):
        wallet.append({
            "kind": "Redeem",
            "icon": "\U0001F381",
            "label": f"Code {row[1]}",
            "amount": _num(row[2]),
            "status": "success",
            "date": row[3],
            "ref": row[0],
        })
    data["wallet"] = wallet
    data["redeem_total"] = sum(w["amount"] for w in wallet)

    # ---- unified timeline ----------------------------------------------
    timeline = []
    for bucket in ("deposits", "purchases", "wallet"):
        for item in data[bucket]:
            timeline.append(item)
    data["timeline"] = timeline
    return data


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _profile_block(d):
    name = f"<code>{d['uid']}</code>"
    tier, need = _tier(d["total_deposited"])
    lines = [
        f"{PE_USER} <b>USER PROFILE</b> \u2014 {name}",
        "",
        f"{PE_MONEY} <b>Balance:</b> {_dual(d['balance'])}",
        f"{PE_DEPOSIT} <b>Total deposited:</b> {_dual(d['total_deposited'])}",
        f"{PE_CART} <b>Total spent:</b> {_dual(d['purchase_total'])}",
        f"{PE_CHART} <b>Profit from user:</b> {_dual(d['profit_total'])}",
        f"{PE_GIFT} <b>Discount:</b> {d['discount']:g}%",
        f"{PE_STAR} <b>Tier:</b> {tier}"
        + (f" <i>({_inr(need)} more to next)</i>" if need else ""),
        f"{PE_CHECK} <b>Status:</b> "
        + ("\U0001F534 Banned" if d["banned"] else "\U0001F7E2 Active"),
        f"{PE_DOC} <b>Joined:</b> {_fmt_date(d['joined'])}",
    ]
    if d.get("referred_by"):
        lines.append(f"{PE_REFER} <b>Referred by:</b> "
                     f"<code>{d['referred_by']}</code>")
    lines.append("")
    lines.append(f"{PE_STATS} <b>Deposits:</b> {d['deposit_count']} "
                 f"\u00b7 <b>Purchases:</b> {d['purchase_count']} "
                 f"\u00b7 <b>Events:</b> {len(d['timeline'])}")
    return "<blockquote expandable>" + "\n".join(lines) + "</blockquote>"


def _item_line(item, show_profit=False):
    badge = _status_badge(item.get("status"))
    line = (f"{item['icon']} <b>{html.escape(_short(item['label']))}</b> \u2014 "
            f"{_inr(item['amount'])}")
    if show_profit and item.get("profit"):
        line += f" <i>(cost {_inr(item.get('cost', 0))} \u00b7 profit {_inr(item['profit'])})</i>"
    line += f"\n     {badge} \u00b7 {_fmt_date(item.get('date'))}"
    if item.get("detail"):
        line += f" \u00b7 <code>{html.escape(str(item['detail']))}</code>"
    return line


def _page(items, page, show_profit=False):
    total = len(items)
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    chunk = items[start:start + PAGE_SIZE]
    body = "\n\n".join(_item_line(i, show_profit) for i in chunk) if chunk \
        else "<i>Nothing recorded yet.</i>"
    return body, page, pages, total


def render_tab(d, tab, page=1):
    """Return (text, buttons) for one tab."""
    uid = d["uid"]
    if tab == "overview":
        text = _profile_block(d)
        if d["deposits"]:
            text += "\n\n" + f"{PE_DEPOSIT} <b>Latest deposit:</b> " \
                             f"{_inr(d['deposits'][0]['amount'])} \u00b7 " \
                             f"{_fmt_date(d['deposits'][0]['date'])}"
        if d["purchases"]:
            last = d["purchases"][0]
            text += "\n" + f"{PE_CART} <b>Latest purchase:</b> " \
                           f"{html.escape(_short(last['label']))} \u00b7 " \
                           f"{_inr(last['amount'])}"
        return text, _tab_buttons(uid, tab)

    if tab == "deposits":
        body, page, pages, total = _page(d["deposits"], page)
        head = (f"{PE_DEPOSIT} <b>DEPOSIT HISTORY</b> \u2014 "
                f"<code>{uid}</code>\n"
                f"{PE_MONEY} <b>Credited:</b> {_dual(d['deposit_total'])} "
                f"\u00b7 <b>Records:</b> {total}\n\n")
        text = "<blockquote expandable>" + head + body + "</blockquote>"
        return text, _tab_buttons(uid, tab, page, pages)

    if tab == "purchases":
        body, page, pages, total = _page(d["purchases"], page, show_profit=True)
        head = (f"{PE_CART} <b>PURCHASE HISTORY</b> \u2014 "
                f"<code>{uid}</code>\n"
                f"{PE_MONEY} <b>Spent:</b> {_dual(d['purchase_total'])} "
                f"\u00b7 <b>Profit:</b> {_inr(d['profit_total'])} "
                f"\u00b7 <b>Orders:</b> {total}\n\n")
        text = "<blockquote expandable>" + head + body + "</blockquote>"
        return text, _tab_buttons(uid, tab, page, pages)

    if tab == "wallet":
        body, page, pages, total = _page(d["wallet"], page)
        head = (f"{PE_MONEY} <b>WALLET ACTIVITY</b> \u2014 "
                f"<code>{uid}</code>\n"
                f"{PE_GIFT} <b>Redeemed:</b> {_inr(d['redeem_total'])} "
                f"\u00b7 <b>Records:</b> {total}\n\n")
        text = "<blockquote expandable>" + head + body + "</blockquote>"
        return text, _tab_buttons(uid, tab, page, pages)

    # timeline
    body, page, pages, total = _page(d["timeline"], page, show_profit=True)
    head = (f"{PE_CHART} <b>FULL TIMELINE</b> \u2014 "
            f"<code>{uid}</code>\n"
            f"{PE_STATS} <b>All actions:</b> {total}\n\n")
    text = "<blockquote expandable>" + head + body + "</blockquote>"
    return text, _tab_buttons(uid, tab, page, pages)


def _tab_buttons(uid, active, page=1, pages=1):
    rows = []
    row = []
    for key, label, icon, fallback, colour in TABS:
        text = ("\u2022 " if key == active else "") + label
        row.append(style_btn(text, f"uh_tab|{uid}|{key}", colour, icon=icon))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if pages > 1:
        nav = []
        if page > 1:
            nav.append(style_btn("\u2B05\uFE0F Prev", f"uh_pg|{uid}|{active}|{page - 1}",
                                 "primary", icon="back"))
        nav.append(style_btn(f"{page}/{pages}", f"uh_pg|{uid}|{active}|{page}",
                             "success", icon="doc"))
        if page < pages:
            nav.append(style_btn("Next \u27A1\uFE0F", f"uh_pg|{uid}|{active}|{page + 1}",
                                 "primary", icon="refresh"))
        rows.append(nav)

    rows.append([
        style_btn("\U0001F504 Refresh", f"uh_home|{uid}", "success", icon="refresh"),
        style_btn("\U0001F50D Another User", "uh_open", "primary", icon="search"),
    ])
    rows.append([
        style_btn("\U0001F4B0 Change Balance", f"uh_bal|{uid}", "primary", icon="money"),
        style_btn("\U0001F6AB Toggle Ban", f"uh_ban|{uid}", "danger", icon="warning"),
    ])
    rows.append([style_btn("\U0001F519 Admin Panel", "adm_adminmain", "danger", icon="back")])
    return rows


async def _send(event, text, buttons):
    try:
        return await event.edit(text, buttons=buttons)
    except Exception:
        try:
            return await event.respond(text, buttons=buttons)
        except Exception:
            return None


async def show_user(event, uid, tab="overview", page=1, note=None):
    d = collect_user_history(uid)
    if not d["exists"] and not d["timeline"]:
        text = (f"{PE_WARNING} <b>No data found for</b> "
                f"<code>{uid}</code>.\n\n"
                f"<i>This user id has never started the bot or made a payment.</i>")
        return await _send(event, text, [[
            style_btn("\U0001F50D Try Another ID", "uh_open", "primary", icon="search"),
            style_btn("\U0001F519 Admin Panel", "adm_adminmain", "danger", icon="back"),
        ]])
    text, buttons = render_tab(d, tab, page)
    if note:
        text = note + "\n\n" + text
    return await _send(event, text, buttons)


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------
def register_user_history(bot):
    def _allowed(uid):
        try:
            return is_admin(uid) and (has_perm(uid, "p_stats") or has_perm(uid, "p_bal"))
        except Exception:
            return is_admin(uid)

    @bot.on(events.NewMessage(pattern=r"(?i)^[/!](uh|userhistory|userinfo)$"))
    async def cmd_user_history(e):
        if not _allowed(e.sender_id):
            return
        uh_state[e.sender_id] = True
        await e.reply(
            f"{PE_SEARCH} <b>User History</b>\n\n"
            f"Send the <b>user id</b> whose full history you want to see.\n"
            f"<i>Example:</i> <code>8347512126</code>",
            buttons=[[style_btn("\u274C Cancel", "uh_cancel", "danger", icon="close")]],
        )

    @bot.on(events.CallbackQuery(pattern=r"^uh_open$"))
    async def cb_uh_open(e):
        if not _allowed(e.sender_id):
            return await e.answer("\u274C Admins only.", alert=True)
        uh_state[e.sender_id] = True
        await e.answer()
        await _send(
            e,
            f"{PE_SEARCH} <b>User History</b>\n\n"
            f"Send the <b>user id</b> whose full history you want to see.\n"
            f"<i>Example:</i> <code>8347512126</code>",
            [[style_btn("\u274C Cancel", "uh_cancel", "danger", icon="close")]],
        )

    @bot.on(events.CallbackQuery(pattern=r"^uh_cancel$"))
    async def cb_uh_cancel(e):
        uh_state.pop(e.sender_id, None)
        await e.answer("Cancelled.")
        from plugins.admin import admin_panel_handler
        try:
            return await admin_panel_handler(e)
        except Exception:
            return await _send(e, "\u274C Cancelled.",
                               [[style_btn("\U0001F519 Admin Panel", "adm_adminmain",
                                           "danger", icon="back")]])

    @bot.on(events.CallbackQuery(pattern=r"^uh_home\|(\d+)$"))
    async def cb_uh_home(e):
        if not _allowed(e.sender_id):
            return await e.answer("\u274C Admins only.", alert=True)
        uid = int(e.pattern_match.group(1))
        await e.answer("Refreshed")
        return await show_user(e, uid, "overview")

    @bot.on(events.CallbackQuery(pattern=r"^uh_tab\|(\d+)\|(\w+)$"))
    async def cb_uh_tab(e):
        if not _allowed(e.sender_id):
            return await e.answer("\u274C Admins only.", alert=True)
        uid = int(e.pattern_match.group(1))
        tab = e.pattern_match.group(2)
        if isinstance(tab, bytes):
            tab = tab.decode()
        if tab not in TAB_KEYS:
            tab = "overview"
        await e.answer()
        return await show_user(e, uid, tab)

    @bot.on(events.CallbackQuery(pattern=r"^uh_pg\|(\d+)\|(\w+)\|(\d+)$"))
    async def cb_uh_pg(e):
        if not _allowed(e.sender_id):
            return await e.answer("\u274C Admins only.", alert=True)
        uid = int(e.pattern_match.group(1))
        tab = e.pattern_match.group(2)
        page = int(e.pattern_match.group(3))
        if isinstance(tab, bytes):
            tab = tab.decode()
        if tab not in TAB_KEYS:
            tab = "overview"
        await e.answer()
        return await show_user(e, uid, tab, page)

    @bot.on(events.CallbackQuery(pattern=r"^uh_bal\|(\d+)$"))
    async def cb_uh_bal(e):
        if not _allowed(e.sender_id):
            return await e.answer("\u274C Admins only.", alert=True)
        uid = int(e.pattern_match.group(1))
        uh_state[e.sender_id] = ("balance", uid)
        await e.answer()
        return await _send(
            e,
            f"{PE_MONEY} <b>Change balance</b> for <code>{uid}</code>\n\n"
            f"Send an amount. Use <code>-50</code> to subtract, <code>+50</code> or "
            f"<code>50</code> to add.",
            [[style_btn("\u274C Cancel", f"uh_home|{uid}", "danger", icon="close")]],
        )

    @bot.on(events.CallbackQuery(pattern=r"^uh_ban\|(\d+)$"))
    async def cb_uh_ban(e):
        if not _allowed(e.sender_id):
            return await e.answer("\u274C Admins only.", alert=True)
        uid = int(e.pattern_match.group(1))
        rows = _q("SELECT banned FROM users WHERE user_id=?", (uid,))
        if not rows:
            return await e.answer("\u274C User not found.", alert=True)
        new_state = 0 if rows[0][0] else 1
        try:
            cur.execute("UPDATE users SET banned=? WHERE user_id=?", (new_state, uid))
            db.commit()
        except Exception as ex:
            logger.error(f"uh_ban failed: {ex}")
            return await e.answer("\u274C Could not update.", alert=True)
        await e.answer("\U0001F534 Banned" if new_state else "\U0001F7E2 Unbanned", alert=True)
        return await show_user(e, uid, "overview")

    # -------------------------------------------------------------- input
    @bot.on(events.NewMessage(func=lambda e: e.sender_id in uh_state))
    async def msg_uh_input(e):
        if not _allowed(e.sender_id):
            uh_state.pop(e.sender_id, None)
            return
        state = uh_state.get(e.sender_id)
        text = (e.raw_text or "").strip()
        if not text or text.startswith("/"):
            return

        if isinstance(state, tuple) and state[0] == "balance":
            target = state[1]
            uh_state.pop(e.sender_id, None)
            try:
                amount = float(text.replace(",", "").replace("\u20b9", "").strip())
            except ValueError:
                uh_state[e.sender_id] = state
                return await e.reply("\u274C Send a number, e.g. <code>50</code> or <code>-50</code>.")
            try:
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?",
                            (amount, target))
                db.commit()
            except Exception as ex:
                logger.error(f"uh balance update failed: {ex}")
                return await e.reply("\u274C Could not update balance.")
            sign = "+" if amount >= 0 else ""
            return await show_user(
                e, target, "overview",
                note=f"{PE_CHECK} <b>Balance updated:</b> "
                     f"{sign}{_inr(amount)}",
            )

        # plain user id
        cleaned = text.replace(",", "").strip()
        if not cleaned.isdigit():
            return await e.reply(
                f"\u274C That is not a valid user id.\nSend digits only, e.g. "
                f"<code>8347512126</code>.")
        uh_state.pop(e.sender_id, None)
        return await show_user(e, int(cleaned), "overview")
