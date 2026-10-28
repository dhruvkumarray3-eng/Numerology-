"""Owner-facing Profit & Pricing console (INR · USDT · profit).

Everything the owner needs to price the bot lives here:

  * a live overview of the global profit rule and the USDT rate
  * per-service profit overrides for
        WhatsApp Account · TG Number Change · All Apps OTP · SMM · LZT
  * a live price preview: enter a panel cost and see exactly what the
    customer will be shown (INR + USDT) and how much the owner keeps
  * one-tap reset for a single service, or for everything at once

The panel's real (cost) price is only ever shown on these admin screens.
"""
from telethon import events

from config import ADMIN_ID, logger
from database import is_admin
from utils.keyboards import style_btn, pe
from utils.markup import (
    SERVICES, SERVICE_ORDER,
    get_markup_config, describe_markup, set_markup,
    get_service_config, set_service_markup, reset_service_markup,
    reset_all_markup, describe_service_markup,
    service_price_breakdown, format_inr, format_usdt, get_usdt_rate,
)

# service -> premium icon key used on its button
SERVICE_ICONS = {
    "whatsapp": "whatsapp",
    "numchange": "numchange",
    "allotp": "allapps_otp",
    "smm": "server",
    "lzt": "telegram",
}

SERVICE_EMOJI = {
    "whatsapp": chr(0x1F4AC),
    "numchange": chr(0x1F501),
    "allotp": chr(0x1F9E9),
    "smm": chr(0x1F6F0),
    "lzt": chr(0x2708) + chr(0xFE0F),
}


def _svc_pe(service):
    """Premium-emoji snippet for a service (message text only)."""
    return pe(SERVICE_ICONS.get(service), SERVICE_EMOJI.get(service, "\u2728"))

# text-entry state: uid -> {"kind": ..., "service": ..., "field": ...}
pf_state = {}

PREVIEW_PRESETS = (10, 50, 100, 500, 1000)


def _is_admin(uid):
    try:
        return bool(is_admin(uid)) or bool(ADMIN_ID and uid == ADMIN_ID)
    except Exception:
        return bool(ADMIN_ID and uid == ADMIN_ID)


async def _render(event, msg, btns):
    try:
        await event.edit(msg, buttons=btns)
    except Exception:
        try:
            await event.respond(msg, buttons=btns)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"profit_admin render failed: {exc}")


def _profit_line(service):
    """'25% · global' style suffix for a service row."""
    cfg = get_service_config(service)
    if cfg["mode"] == "percent":
        text = f"{cfg['percent']:g}%"
    else:
        symbol = chr(0x20B9) if cfg["currency"] == "INR" else "$"
        text = f"{symbol}{cfg['fixed']:g} ({cfg['currency']})"
    return text + (" · custom" if cfg.get("override") else " · global")


def _example_line(service, cost=100):
    b = service_price_breakdown(cost, service)
    return (f"{format_inr(cost)} cost {chr(0x2192)} {format_inr(b['inr'])} · "
            f"{format_usdt(b['usdt'])} · profit {format_inr(b['profit_inr'])}")


# ---------------------------------------------------------------------------
# Home screen
# ---------------------------------------------------------------------------
async def show_profit_home(event, note=None):
    cfg = get_markup_config()
    rate = get_usdt_rate()

    i_money = pe("money", chr(0x1F4B0))
    i_chart = pe("chart", chr(0x1F4CA))
    i_stats = pe("stats", chr(0x1F4C8))
    i_globe = pe("globe", chr(0x1F30D))
    i_check = pe("check", chr(0x2705))

    rows = []
    for service in SERVICE_ORDER:
        rows.append(
            f"{_svc_pe(service)} <b>{SERVICES[service]}</b> — {_profit_line(service)}\n"
            f"     <i>{_example_line(service)}</i>"
        )

    head = (
        f"<blockquote expandable>{i_money} <b>PROFIT &amp; PRICING</b> — "
        f"<b>INR · USDT</b>\n\n"
        f"{i_chart} <b>Global rule:</b> {describe_markup(cfg)}\n"
        f"{i_globe} <b>USDT rate:</b> {format_inr(rate)} = 1 USDT\n"
        f"{i_stats} <b>Services priced separately:</b> {len(SERVICE_ORDER)}\n\n"
        + "\n".join(rows)
        + f"\n\n{i_check} <i>Users always see BOTH ₹INR and USDT. "
          f"The real panel cost is never shown to them.</i>"
    )
    if note:
        head += f"\n\n{note}"
    head += "</blockquote>"

    btns = []
    for service in SERVICE_ORDER:
        btns.append([style_btn(
            f"{SERVICE_EMOJI[service]} {SERVICES[service]} · {_profit_line(service)}",
            f"pf_svc|{service}", "primary", icon=SERVICE_ICONS[service])])
    btns.append([
        style_btn(chr(0x1F4B8) + " Live Price Preview", "pf_preview", "success", icon="money"),
        style_btn(chr(0x2699) + chr(0xFE0F) + " Set Global Profit", "pf_global", "success", icon="settings"),
    ])
    btns.append([
        style_btn(chr(0x267B) + chr(0xFE0F) + " Reset All Profit", "pf_resetall", "danger", icon="warning"),
        style_btn(chr(0x1F519) + " Back to Admin", "adm_adminmain", "danger", icon="back"),
    ])
    await _render(event, head, btns)


# ---------------------------------------------------------------------------
# Per-service screen
# ---------------------------------------------------------------------------
async def show_service(event, service):
    if service not in SERVICES:
        return await show_profit_home(event, "⚠️ Unknown service.")

    cfg = get_service_config(service)
    rate = get_usdt_rate()
    state = "custom override" if cfg.get("override") else "following global rule"

    i_money = pe("money", chr(0x1F4B0))
    i_chart = pe("chart", chr(0x1F4CA))
    i_stats = pe("stats", chr(0x1F4C8))
    i_globe = pe("globe", chr(0x1F30D))

    preview = []
    for cost in (10, 50, 100, 500):
        b = service_price_breakdown(cost, service)
        preview.append(
            f"• {format_inr(cost)} → <b>{format_inr(b['inr'])}</b> · "
            f"{format_usdt(b['usdt'])} <i>(profit {format_inr(b['profit_inr'])})</i>"
        )

    msg = (
        f"<blockquote expandable>{_svc_pe(service)} "
        f"<b>{SERVICES[service]} — Profit Settings</b>\n\n"
        f"{i_chart} <b>Status:</b> {state}\n"
        f"{i_money} <b>Rule:</b> {describe_service_markup(service)}\n"
        f"{i_globe} <b>USDT rate:</b> {format_inr(rate)} = 1 USDT\n\n"
        f"{i_stats} <b>Live preview</b> (panel cost → customer price)\n"
        + "\n".join(preview)
        + "</blockquote>"
    )

    btns = [
        [style_btn(chr(0x1F4C8) + " Percent profit", f"pf_set|{service}|percent", "success", icon="chart"),
         style_btn(chr(0x20B9) + " Fixed INR", f"pf_set|{service}|fixed_inr", "primary", icon="money")],
        [style_btn("$ Fixed USDT", f"pf_set|{service}|fixed_usd", "primary", icon="money")],
    ]
    if cfg.get("override"):
        btns.append([style_btn(chr(0x267B) + chr(0xFE0F) + " Use global rule instead",
                               f"pf_off|{service}", "danger", icon="warning")])
    btns.append([
        style_btn(chr(0x1F4B8) + " Preview this service", f"pf_prevsvc|{service}", "success", icon="money"),
        style_btn(chr(0x1F519) + " Back", "pf_home", "danger", icon="back"),
    ])
    await _render(event, msg, btns)


# ---------------------------------------------------------------------------
# Global screen
# ---------------------------------------------------------------------------
async def show_global(event):
    cfg = get_markup_config()
    rate = get_usdt_rate()

    i_money = pe("money", chr(0x1F4B0))
    i_chart = pe("chart", chr(0x1F4CA))
    i_globe = pe("globe", chr(0x1F30D))
    i_stats = pe("stats", chr(0x1F4C8))

    preview = []
    for cost in (10, 50, 100, 500):
        b = service_price_breakdown(cost, "whatsapp")
        preview.append(f"• {format_inr(cost)} → <b>{format_inr(b['inr'])}</b> · {format_usdt(b['usdt'])}")

    msg = (
        f"<blockquote expandable>{i_chart} <b>GLOBAL PROFIT</b>\n\n"
        f"{i_money} <b>Rule:</b> {describe_markup(cfg)}\n"
        f"{i_globe} <b>USDT rate:</b> {format_inr(rate)} = 1 USDT\n\n"
        f"{i_stats} <b>Preview on a global-priced service</b>\n"
        + "\n".join(preview)
        + "\n\n<i>Services with a custom override ignore this rule.</i></blockquote>"
    )

    btns = [
        [style_btn(chr(0x1F4C8) + " Percent profit", "pf_gset|percent", "success", icon="chart"),
         style_btn(chr(0x20B9) + " Fixed INR", "pf_gset|fixed_inr", "primary", icon="money")],
        [style_btn("$ Fixed USDT", "pf_gset|fixed_usd", "primary", icon="money")],
        [style_btn(chr(0x1F519) + " Back", "pf_home", "danger", icon="back")],
    ]
    await _render(event, msg, btns)


# ---------------------------------------------------------------------------
# Live price preview
# ---------------------------------------------------------------------------
def _preview_table(cost, service=None):
    """Rows of cost -> profit -> INR -> USDT for one cost across services."""
    targets = [service] if service else list(SERVICE_ORDER)
    lines = []
    for key in targets:
        b = service_price_breakdown(cost, key)
        lines.append(
            f"{_svc_pe(key)} <b>{SERVICES[key]}</b>\n"
            f"     cost {format_inr(cost)} → user pays <b>{format_inr(b['inr'])}</b> · "
            f"{format_usdt(b['usdt'])}\n"
            f"     you keep <b>{format_inr(b['profit_inr'])}</b>"
        )
    return "\n".join(lines)


async def show_preview(event, cost=100, service=None):
    rate = get_usdt_rate()
    i_money = pe("money", chr(0x1F4B0))
    i_stats = pe("stats", chr(0x1F4C8))
    i_globe = pe("globe", chr(0x1F30D))

    title = (f"{_svc_pe(service)} {SERVICES[service]}" if service
             else "All services")
    msg = (
        f"<blockquote expandable>{i_money} <b>LIVE PRICE PREVIEW</b> — {title}\n\n"
        f"{i_globe} <b>USDT rate:</b> {format_inr(rate)} = 1 USDT\n"
        f"{i_stats} <b>Panel cost:</b> {format_inr(cost)}\n\n"
        + _preview_table(cost, service)
        + "\n\n<i>Tap a preset below or send any amount to preview it live.</i></blockquote>"
    )

    btns = []
    row = []
    for preset in PREVIEW_PRESETS:
        data = f"pf_prev|{preset}" + (f"|{service}" if service else "")
        row.append(style_btn(format_inr(preset), data, "primary", icon="money"))
        if len(row) == 3:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    custom = f"pf_prevask|{service}" if service else "pf_prevask"
    btns.append([style_btn(chr(0x270F) + chr(0xFE0F) + " Custom amount", custom, "success", icon="search")])
    back = f"pf_svc|{service}" if service else "pf_home"
    btns.append([style_btn(chr(0x1F519) + " Back", back, "danger", icon="back")])
    await _render(event, msg, btns)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def register_profit_admin(bot):

    @bot.on(events.NewMessage(pattern=r"(?i)^[/!](profit|pricing|profitpanel)$"))
    async def cmd_profit(e):
        if not _is_admin(e.sender_id):
            return
        pf_state.pop(e.sender_id, None)
        await show_profit_home(e)

    @bot.on(events.CallbackQuery(pattern=r"^pf_home$"))
    async def cb_pf_home(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        pf_state.pop(e.sender_id, None)
        await e.answer()
        await show_profit_home(e)

    @bot.on(events.CallbackQuery(pattern=r"^pf_svc\|(\w+)$"))
    async def cb_pf_svc(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        service = e.pattern_match.group(1).decode()
        pf_state.pop(e.sender_id, None)
        await e.answer()
        await show_service(e, service)

    @bot.on(events.CallbackQuery(pattern=r"^pf_global$"))
    async def cb_pf_global(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        pf_state.pop(e.sender_id, None)
        await e.answer()
        await show_global(e)

    @bot.on(events.CallbackQuery(pattern=r"^pf_preview$"))
    async def cb_pf_preview(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        await e.answer()
        await show_preview(e, 100)

    @bot.on(events.CallbackQuery(pattern=r"^pf_prevsvc\|(\w+)$"))
    async def cb_pf_prevsvc(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        service = e.pattern_match.group(1).decode()
        await e.answer()
        await show_preview(e, 100, service)

    @bot.on(events.CallbackQuery(pattern=r"^pf_prev\|(\d+)(?:\|(\w+))?$"))
    async def cb_pf_prev(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        cost = float(e.pattern_match.group(1).decode())
        raw = e.pattern_match.group(2)
        service = raw.decode() if raw else None
        await e.answer()
        await show_preview(e, cost, service)

    @bot.on(events.CallbackQuery(pattern=r"^pf_prevask(?:\|(\w+))?$"))
    async def cb_pf_prevask(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        raw = e.pattern_match.group(1)
        service = raw.decode() if raw else None
        pf_state[e.sender_id] = {"kind": "preview", "service": service}
        await e.answer("Send an amount")
        await _render(
            e,
            f"<blockquote>{pe('money', chr(0x1F4B0))} <b>Live price preview</b>\n\n"
            "Send the panel cost in ₹ (e.g. <code>250</code>).</blockquote>",
            [[style_btn(chr(0x1F519) + " Cancel", "pf_home", "danger", icon="back")]],
        )

    @bot.on(events.CallbackQuery(pattern=r"^pf_set\|(\w+)\|(\w+)$"))
    async def cb_pf_set(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        service = e.pattern_match.group(1).decode()
        field = e.pattern_match.group(2).decode()
        if service not in SERVICES:
            return await e.answer("Unknown service.", alert=True)
        pf_state[e.sender_id] = {"kind": "service", "service": service, "field": field}
        await e.answer("Send the value")
        label = {
            "percent": "profit percentage (e.g. <code>40</code>)",
            "fixed_inr": "fixed ₹ profit per sale (e.g. <code>35</code>)",
            "fixed_usd": "fixed USDT profit per sale (e.g. <code>0.5</code>)",
        }.get(field, "value")
        await _render(
            e,
            f"<blockquote>{_svc_pe(service)} <b>{SERVICES[service]}</b>\n\n"
            f"Send the {label}.</blockquote>",
            [[style_btn(chr(0x1F519) + " Cancel", f"pf_svc|{service}", "danger", icon="back")]],
        )

    @bot.on(events.CallbackQuery(pattern=r"^pf_gset\|(\w+)$"))
    async def cb_pf_gset(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        field = e.pattern_match.group(1).decode()
        pf_state[e.sender_id] = {"kind": "global", "field": field}
        await e.answer("Send the value")
        label = {
            "percent": "profit percentage (e.g. <code>25</code>)",
            "fixed_inr": "fixed ₹ profit per sale (e.g. <code>20</code>)",
            "fixed_usd": "fixed USDT profit per sale (e.g. <code>0.25</code>)",
        }.get(field, "value")
        await _render(
            e,
            f"<blockquote>{pe('chart', chr(0x1F4CA))} <b>Global profit</b>\n\n"
            f"Send the {label}.</blockquote>",
            [[style_btn(chr(0x1F519) + " Cancel", "pf_global", "danger", icon="back")]],
        )

    @bot.on(events.CallbackQuery(pattern=r"^pf_off\|(\w+)$"))
    async def cb_pf_off(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        service = e.pattern_match.group(1).decode()
        reset_service_markup(service)
        await e.answer("Override removed")
        await show_service(e, service)

    @bot.on(events.CallbackQuery(pattern=r"^pf_resetall$"))
    async def cb_pf_resetall(e):
        if not _is_admin(e.sender_id):
            return await e.answer("Admins only.", alert=True)
        reset_all_markup()
        await e.answer("All profit reset")
        cfg = get_markup_config()
        await show_profit_home(
            e,
            f"{pe('check', chr(0x2705))} <b>Profit reset in INR.</b> "
            f"Now <b>{describe_markup(cfg)}</b> · "
            f"{format_inr(get_usdt_rate())} = 1 USDT · all service overrides cleared.")

    # ---- text input router ------------------------------------------------
    @bot.on(events.NewMessage(func=lambda e: e.sender_id in pf_state
                              and not (e.text or "").startswith("/")))
    async def msg_pf_input(e):
        uid = e.sender_id
        state = pf_state.pop(uid, None)
        if not state:
            return
        raw = (e.text or "").strip().replace(",", "").replace("₹", "")
        try:
            value = float(raw)
        except ValueError:
            pf_state[uid] = state
            return await e.reply(
                f"{pe('warning', chr(0x26A0) + chr(0xFE0F))} "
                "<b>Send a number only</b>, e.g. <code>25</code>.")
        if value < 0:
            pf_state[uid] = state
            return await e.reply(
                f"{pe('warning', chr(0x26A0) + chr(0xFE0F))} Value cannot be negative.")

        kind = state.get("kind")
        if kind == "preview":
            await show_preview(e, value, state.get("service"))
            raise events.StopPropagation

        field = state.get("field")
        if kind == "service":
            service = state["service"]
            if field == "percent":
                set_service_markup(service, mode="percent", percent=value)
            elif field == "fixed_inr":
                set_service_markup(service, mode="fixed", fixed=value, currency="INR")
            elif field == "fixed_usd":
                set_service_markup(service, mode="fixed", fixed=value, currency="USD")
            await show_service(e, service)
        elif kind == "global":
            if field == "percent":
                set_markup(mode="percent", percent=value)
            elif field == "fixed_inr":
                set_markup(mode="fixed", fixed=value, currency="INR")
            elif field == "fixed_usd":
                set_markup(mode="fixed", fixed=value, currency="USD")
            await show_global(e)
        raise events.StopPropagation
