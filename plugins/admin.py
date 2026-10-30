import os
import csv
import zipfile
import shutil
import html
import time
from telethon import events, Button, TelegramClient
from telethon.tl.functions.account import GetPasswordRequest
from telethon.errors import SessionPasswordNeededError
from database import cur, db, is_bot_online, is_admin, has_perm, ADMIN_ID, get_flag_by_country_name, get_country_info, update_balance, get_bot_mode, get_change_number_fee, get_lzt_margin, set_lzt_margin
from config import PE_CROWN, PE_CHECK, PE_GIFT, PE_LOCATION, PE_LIGHTNING, P_USERS, P_PKG, P_WAIT, P_ON, P_YES, P_NO, P_WARN, P_DOC, P_FLAG, PE_MONEY, PE_USDT, PE_STATS, P_MONEY, P_PHONE, P_GLOBE, P_2FA, P_CAL, P_OTP, P_CARD, P_TG, P_ACC, P_USDT, P_UPI, P_CART, P_GIFT, P_STATS, P_OFF, API_ID, API_HASH, bot, is_super_admin
from utils.keyboards import style_btn, SEARCH_EMOJI_ID
from utils.smm_client import is_server_enabled, SMM_SERVERS

async def admin_panel_handler(event):
    uid = event.sender_id
    if not is_admin(uid): return
    
    status_text = "🟢 Bot is ON" if is_bot_online() else "🔴 Bot is OFF"
    current_mode = get_bot_mode()
    mode_text = "📂 Manual" if current_mode == 'manual' else ("🌐 Panel (LZT)" if current_mode == 'panel' else "⚡ Hybrid")
    total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_stock = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
    pending_deposits = cur.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0]
    chg_fee = get_change_number_fee()
    btns = []
    
    if is_super_admin(uid) or has_perm(uid, 'p_settings'):
        btns.append([
            style_btn(f"Status: {status_text}", "adm_togglebot", "primary", icon=5409098988156629257),
            style_btn(f"Mode: {mode_text}", "adm_toggle_mode", "success", icon=5409271925014801629)
        ])
        # Owner-controlled SMM server switches (turn server 1 / 2 ON or OFF).
        smm1 = "\U0001F7E2 ON" if is_server_enabled(1) else "\U0001F534 OFF"
        smm2 = "\U0001F7E2 ON" if is_server_enabled(2) else "\U0001F534 OFF"
        btns.append([
            style_btn(f"\U0001F6F0 SMM Server 1: {smm1}", "adm_togglesmm|1", "success", icon=5408995930416362034),
            style_btn(f"\U0001F6F0 SMM Server 2: {smm2}", "adm_togglesmm|2", "danger", icon=5409320020058584473)
        ])
        btns.append([style_btn("\U0001F5A5 Manage Servers (Basic TG / Num / etc.)", "adm_servers", "primary", icon=5409098988156629257)])
        btns.append([style_btn("\U0001F6E0 Advanced Tools & Analytics (Panels \u00b7 DB \u00b7 SMM \u00b7 Grant \u00b7 Packs)", "hub_open", "success", icon="settings")])
        btns.append([style_btn("\U0001F504 Update Bot from GitHub", "adm_updatebot", "primary", icon=5409271925014801629)])
        
    r1 = []
    if is_super_admin(uid) or has_perm(uid, 'p_add_stock'):
        r1.extend([style_btn("Add Single Acc", "adm_addstock", "primary", icon=6129732880529628243), style_btn("Add ZIP", "adm_addzip", "primary", icon=5355292788923593967)])
    if r1: btns.append(r1)

    r2 = []
    if is_super_admin(uid) or has_perm(uid, 'p_manage_stock'):
        r2.extend([style_btn("Manage Stock", "adm_managestock", "success", icon=6129731974291527294), style_btn("Check Stock", "adm_checkstock", "primary", icon=5409098988156629257), style_btn("Auto Price", "adm_autoprice", "primary", icon=5409098988156629257)])
    if r2: btns.append(r2)

    if is_super_admin(uid) or has_perm(uid, 'p_manage_stock'):
        btns.append([style_btn("🛍 Product Catalogs (Panels · ZIPs)", "adm_catalogs", "success", icon=5409320020058584473)])

    r3 = []
    if is_super_admin(uid) or has_perm(uid, 'p_stats'):
        r3.extend([style_btn("Statistics", "adm_stats", "primary", icon=5409098988156629257), style_btn("Broadcast", "adm_bcast", "primary", icon=5409098988156629257)])
        r3.append(style_btn("\U0001F50D User History (Deposits \u00b7 Orders \u00b7 Timeline)",
                            "uh_open", "success", icon="search"))
    if r3: btns.append(r3)

    r4 = []
    if is_super_admin(uid) or has_perm(uid, 'p_bal'):
        r4.extend([style_btn("Change Balance", "adm_bal", "primary", icon=6129888444245089008), style_btn("Ban User", "adm_ban", "danger", icon=5408832111773757273)])
    if r4: btns.append(r4)

    r5 = []
    if is_super_admin(uid) or has_perm(uid, 'p_settings'):
        r5.extend([style_btn("Discount", "adm_discount", "primary", icon=5409098988156629257), style_btn("Ref %", "adm_refpct", "primary", icon=5409098988156629257)])
        btns.append(r5)
        btns.append([style_btn("📢 Channels & FSub", "adm_channels_mgr", "success", icon=6129627894349045589), style_btn("Support URL", "adm_supporturl", "primary", icon=5409098988156629257)])
        btns.append([style_btn("💳 Auto-UPI / IMAP", "adm_autoupi", "success", icon=5409271925014801629), style_btn("🌐 LZT Panel Settings", "adm_lzt_settings", "primary", icon=5409166771330494453)])
        btns.append([style_btn("⚙️ Search & Quality Settings", "adm_search_settings", "success", icon=SEARCH_EMOJI_ID)])
        btns.append([style_btn("📧 Temp Mail (API)", "adm_tempmail", "primary", icon=5796209712009581332), style_btn("🔐 OTP / SMS Key", "adm_otp", "success", icon=5796209712009581332)])
        btns.append([style_btn("💰 Trust Wallet / USDT", "adm_trustwallet", "success", icon=5409271925014801629), style_btn("🏦 UPI Settings", "adm_upi", "primary", icon=5409098988156629257)])
        btns.append([style_btn("📦 Add Source Code (ZIP)", "adm_addsrc", "success", icon=5951663025336356427), style_btn("🗑 Delete Source Code", "adm_delsrc", "danger", icon=6129888444245089008)])
        btns.append([style_btn("💰 Profit & Pricing (INR · USDT)", "pf_home", "success", icon="money")])
        btns.append([style_btn(f"🔄 Change Num Fee: ₹{chg_fee}", "adm_setchangefee", "success", icon=5409320020058584473), style_btn("Set USDT Rate", "adm_usdtrate", "primary", icon=5409098988156629257)])
        btns.append([style_btn("Payments", "adm_payments", "primary", icon=5409098988156629257), style_btn("Manage Admins", "adm_manageadmins", "primary", icon=5409098988156629257)])
        btns.append([style_btn("𝐁ᴀᴄᴋup Users", "adm_backupusr", "primary", icon=5409098988156629257), style_btn("Restore Users", "adm_restoreusr", "primary", icon=5409098988156629257)])
        btns.append([style_btn("🗑 Cleanup & Delete (Stock · Panels · Codes)", b"ac_menu", "danger", icon=5408832111773757273)])
        btns.append([style_btn("🆘 Help & All Commands", b"help_admin", "success", icon=6129732880529628243)])
        btns.append([style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐌ᴀɪɴ 𝐌ᴇɴᴜ", b"dashboard_main", "danger", icon=6129812419028982717)])

    # Live profit snapshot: global rule, USDT rate and profit earned so far.
    try:
        from utils.markup import describe_markup as _describe_markup, get_usdt_rate as _get_usdt_rate
        _profit_rule = _describe_markup()
        _usdt_rate = _get_usdt_rate()
    except Exception:
        _profit_rule = "\u2014"
        _usdt_rate = 0
    try:
        _earned = cur.execute(
            "SELECT COALESCE(SUM(profit),0) FROM panel_orders").fetchone()[0] or 0
    except Exception:
        _earned = 0

    header = (f"<blockquote>{PE_CROWN} <b>\U0001d400\u1d05\u1d20\u1d00\u0274\u1d04\u1d07\u1d05 \U0001d400\u1d05\u1d0d\u026a\u0274 \U0001d403\u1d00s\u029c\u0299\u1d0f\u1d00\u0280\u1d05</b>\n\n"
              f"{PE_LIGHTNING} <b>\U0001d40c\u1d0f\u1d05\u1d07:</b> {mode_text}\n"
              f"{PE_CHECK} \U0001d414s\u1d07\u0280s: <b>{total_users}</b>\n"
              f"{PE_GIFT} \U0001d400\u1d20\u1d00\u026a\u029f\u1d00\u0299\u029f\u1d07 \U0001d412\u1d1b\u1d0f\u1d04\u1d0b: <b>{total_stock}</b>\n"
              f"{PE_LIGHTNING} \U0001d40f\u1d07\u0274\u1d05\u026a\u0274\u0262 \U0001d403\u1d07\u1d18\u1d0fs\u026a\u1d1bs: <b>{pending_deposits}</b>\n"
              f"{PE_CHECK} <b>\U0001d400\u1d05\u1d0d\u026a\u0274 \U0001d408\U0001d403:</b> <code>{uid}</code>\n"
              f"{PE_MONEY} <b>\U0001d40f\u0280\u1d0f\u0493\u026a\u1d1b:</b> {_profit_rule}\n"
              f"{PE_USDT} <b>1 USDT:</b> \u20b9{_usdt_rate:g}\n"
              f"{PE_STATS} <b>\U0001d40f\u0280\u1d0f\u0493\u026a\u1d1b \u1d07\u1d00\u0280\u0274\u1d07\u1d05:</b> \u20b9{_earned:,.0f}\n"
              f"{PE_GIFT} <b>\U0001d40e\u1d21\u0274\u1d07\u0280 \U0001d408\U0001d403:</b> <code>{ADMIN_ID}</code>"
              + (f"\n{PE_CROWN} <b>\U0001d412\u1d1c\u1d18\u1d07\u0280 \U0001d400\u1d05\u1d0d\u026a\u0274 \U0001d408\U0001d403:</b> <code>{uid}</code>" if is_super_admin(uid) else "")
              + "</blockquote>")
    try: await event.edit(header, buttons=btns)
    except: await bot.send_message(event.chat_id, header, buttons=btns)

def register_admin(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^([/!]?admin|🔐 𝐀ᴅᴍɪɴ 𝐏ᴀɴᴇʟ|🔐 Admin Panel)$"))
    async def msg_admin(e):
        await admin_panel_handler(e)

    # ==================================================================
    #  TEMP MAIL — fully editable from the panel
    # ==================================================================
    #  Before this screen existed the panel could only *display* the key
    #  that was baked into config.py, so the owner had no way to switch
    #  provider or rotate a key without a redeploy.  Every value below is
    #  written to the SQLite `settings` table (utils/runtime_config.py) and
    #  takes effect on the very next request — no restart.
    # ==================================================================
    async def _tm_panel_text():
        from utils import tempmail as tm
        from utils import runtime_config
        cfg = tm.settings()
        info = await tm.health()
        ok = info.get("ok")
        head = "\u2705 Working" if ok else "\u274c Not working"
        on_txt = "\U0001F7E2 ON \u2014 users can use Free Temp Mail" if cfg.get("enabled") \
            else "\U0001F534 OFF \u2014 button hidden from users"
        lines = [
            "<blockquote expandable>\U0001F4E7 <b>TEMP MAIL \u2014 API SETTINGS</b>\n\n",
            f"\U0001F50C <b>Provider:</b> <code>grabmail.io</code>\n",
            f"\U0001F6A6 <b>For users:</b> {on_txt}\n",
            f"\U0001F511 <b>API Key:</b> <code>{html.escape(runtime_config.mask(cfg.get('api_key', '')))}</code>",
            f" <i>({html.escape(cfg.get('source') or 'env')})</i>\n",
            f"\U0001F310 <b>Base URL:</b> <code>{html.escape(str(cfg.get('base_url')))}</code>\n",
            f"\U0001F517 <b>Website Link:</b> <code>{html.escape(str(cfg.get('website_url') or '-'))}</code>\n",
            f"\U0001F5C2 <b>Domain:</b> <code>{html.escape(str(cfg.get('domain') or 'auto'))}</code>\n",
            f"\U0001F4E1 <b>Status:</b> {head}\n",
        ]
        if ok:
            if info.get("plan"):
                lines.append(f"\U0001F4CA <b>Plan:</b> {html.escape(str(info.get('plan')))}\n")
            if info.get("quota"):
                lines.append(
                    f"\U0001F4E6 <b>Allowance:</b> {info.get('left')} / {info.get('quota')} left\n")
            if info.get("domains"):
                lines.append(f"\U0001F5C2 <b>Domains available:</b> {info.get('domains')}\n")
        elif info.get("error"):
            lines.append(f"\u26A0\ufe0f <b>Error:</b> {html.escape(str(info.get('error'))[:220])}\n")
        lines.append(
            "\n<i>Values are saved in the bot database, so a restart or a "
            "redeploy keeps them. The environment variable is only the "
            "fallback when nothing is saved here.</i></blockquote>")
        return "".join(lines)

    def _tm_buttons():
        from utils import runtime_config
        is_on = runtime_config.tempmail_enabled()
        toggle = (style_btn("\U0001F534 Turn OFF for users", "adm_tm_toggle", "danger",
                            icon=5408832111773757273)
                  if is_on else
                  style_btn("\U0001F7E2 Turn ON for users", "adm_tm_toggle", "success",
                            icon=5796209712009581332))
        return [
            [toggle],
            [style_btn("\U0001F511 Change API Key", "adm_tm_key", "success", icon=5796209712009581332),
             style_btn("\U0001F310 Change Base URL", "adm_tm_base", "primary", icon=5409098988156629257)],
            [style_btn("\U0001F517 Change Website Link", "adm_tm_website", "primary", icon=5409098988156629257),
             style_btn("\U0001F5C2 Change Domain", "adm_tm_domain", "primary", icon=5409098988156629257)],
            [style_btn("\U0001F9EA Test Create Inbox", "adm_tm_test", "success", icon=5796209712009581332),
             style_btn("\U0001F504 Refresh", "adm_tm_refresh", "primary", icon=5408995930416362034)],
            [style_btn("\u267B\ufe0f Reset to ENV", "adm_tm_reset", "danger", icon=5408832111773757273)],
            [style_btn("\U0001F519 Back", "adm_adminmain", "danger", icon=6129812419028982717)],
        ]

    @bot.on(events.CallbackQuery(pattern=r"^adm_tempmail$"))
    async def cb_adm_tempmail(e):
        if not is_admin(e.sender_id):
            return
        text = await _tm_panel_text()
        try:
            await e.edit(text, buttons=_tm_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_refresh$"))
    async def cb_adm_tm_refresh(e):
        if not is_admin(e.sender_id):
            return
        text = await _tm_panel_text()
        try:
            await e.edit(text, buttons=_tm_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_toggle$"))
    async def cb_adm_tm_toggle(e):
        if not is_admin(e.sender_id):
            return
        from utils import runtime_config
        new_state = not runtime_config.tempmail_enabled()
        runtime_config.set("tempmail_enabled", "on" if new_state else "off")
        await e.answer("Temp Mail ON for users" if new_state else "Temp Mail OFF for users",
                       alert=False)
        text = await _tm_panel_text()
        try:
            await e.edit(text, buttons=_tm_buttons())
        except Exception:
            pass

    async def _tm_wizard(e, prompt, key, validator=None, success=""):
        """Shared single-value editor: ask, validate, persist, return to panel."""
        if not is_admin(e.sender_id):
            return
        from utils import runtime_config
        chat = e.chat_id
        await e.answer()
        async with bot.conversation(chat, timeout=300) as conv:
            await conv.send_message(prompt + "\n\n<i>Type /cancel to abort.</i>")
            resp = await conv.get_response()
            raw = (resp.text or "").strip()
            if raw.lower() in ("/cancel", "cancel"):
                await conv.send_message("\u2139\ufe0f Cancelled \u2014 nothing changed.")
            else:
                problem = validator(raw) if validator else None
                if problem:
                    await conv.send_message(f"\u274c {problem}\nNothing changed.")
                else:
                    saved = runtime_config.set(key, raw)
                    note = success or "Saved."
                    if not saved:
                        note += ("\n\u26A0\ufe0f The database write failed, so this value "
                                 "is live only until the bot restarts.")
                    await conv.send_message(f"\u2705 {note}\n\n<code>{html.escape(raw[:80])}</code>")
        text = await _tm_panel_text()
        try:
            await e.edit(text, buttons=_tm_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_key$"))
    async def cb_adm_tm_key(e):
        if not is_admin(e.sender_id):
            return
        await _tm_wizard(
            e,
            ("<blockquote>\U0001F511 <b>Send the new Grabmail API key</b>\n\n"
             "Example: <code>gm_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</code>\n\n"
             "Get it from grabmail.io \u2192 Dashboard \u2192 API. The key is stored "
             "in the bot database and shown masked from now on.\n\n"
             "<i>Optional \u2014 the free public domains work without a key.</i>"
             "</blockquote>"),
            "tempmail_api_key",
            validator=lambda v: None if len(v) >= 8 else "That looks too short for an API key.",
            success="Grabmail API key updated.",
        )

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_base$"))
    async def cb_adm_tm_base(e):
        if not is_admin(e.sender_id):
            return
        await _tm_wizard(
            e,
            ("<blockquote>\U0001F310 <b>Send the Grabmail API base URL</b>\n\n"
             "Default: <code>https://grabmail.io/api/v1</code>\n\n"
             "<i>No trailing slash needed.</i></blockquote>"),
            "tempmail_base_url",
            validator=lambda v: None if v.startswith("http") else "The URL must start with http:// or https://",
            success="Base URL updated.",
        )

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_website$"))
    async def cb_adm_tm_website(e):
        if not is_admin(e.sender_id):
            return
        await _tm_wizard(
            e,
            ("<blockquote>\U0001F517 <b>Send the Temp Mail website link</b>\n\n"
             "Default: <code>https://grabmail.io</code>\n\n"
             "This is shown to users as the \"open website\" link.</blockquote>"),
            "tempmail_website_url",
            validator=lambda v: None if v.startswith("http") else "The URL must start with http:// or https://",
            success="Website link updated.",
        )

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_domain$"))
    async def cb_adm_tm_domain(e):
        if not is_admin(e.sender_id):
            return
        await _tm_wizard(
            e,
            ("<blockquote>\U0001F5C2 <b>Send the domain for new inboxes</b>\n\n"
             "Grabmail free: <code>grabmail.io</code> \u00b7 <code>mixozia.com</code> "
             "\u00b7 <code>linqmail.com</code>\n"
             "Premium domains need a paid Grabmail plan.\n\n"
             "Send <code>auto</code> to let the provider pick.</blockquote>"),
            "tempmail_domain",
            validator=lambda v: None if ("." in v or v == "auto") else "That does not look like a domain.",
            success="Domain updated.",
        )

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_reset$"))
    async def cb_adm_tm_reset(e):
        if not is_admin(e.sender_id):
            return
        from utils import runtime_config
        for key in ("tempmail_api_key", "tempmail_base_url", "tempmail_website_url",
                    "tempmail_domain", "tempmail_account_email", "tempmail_account_password"):
            runtime_config.clear(key)
        await e.answer("Reset to environment values", alert=False)
        text = await _tm_panel_text()
        try:
            await e.edit(text, buttons=_tm_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_test$"))
    async def cb_adm_tm_test(e):
        if not is_admin(e.sender_id):
            return
        from utils import tempmail as tm
        try:
            data = await tm.test_connection()
            text = (f"<blockquote>\u2705 <b>Temp Mail works!</b>\n\n"
                    f"\U0001F50C Provider: <code>{html.escape(str(data.get('provider')))}</code>\n"
                    f"\U0001F4E7 Address: <code>{html.escape(str(data.get('email')))}</code>\n"
                    f"\u23f3 Retention: {html.escape(str(data.get('expire_at') or 'n/a'))}</blockquote>")
        except Exception as ex:
            text = (f"<blockquote>\u274c <b>Temp Mail test failed</b>\n\n"
                    f"{html.escape(str(ex)[:300])}\n\n"
                    "<i>Check the API key and base URL above.</i></blockquote>")
        btns = [[style_btn("\U0001F519 Back", "adm_tempmail", "danger", icon=6129812419028982717)]]
        try:
            await e.edit(text, buttons=btns)
        except Exception:
            pass

    # ==================================================================
    #  OTP / SMS PROVIDERS (TemporaSMS) — also editable from the panel
    # ==================================================================
    async def _otp_panel_text():
        from utils import temporasms
        from utils import runtime_config
        cfg = temporasms._settings()
        key = cfg.get("api_key") or ""
        status_txt = ("\u2705 Configured" if temporasms.configured()
                      else "\u274c Not configured")
        lines = [
            "<blockquote expandable>\U0001F510 <b>OTP / SMS PROVIDER \u2014 TemporaSMS</b>\n\n",
            f"\U0001F511 <b>API Key:</b> <code>{html.escape(runtime_config.mask(key))}</code>",
            f" <i>({html.escape(cfg.get('source') or 'env')})</i>\n",
            f"\U0001F310 <b>Base URL:</b> <code>{html.escape(str(cfg.get('base_url')))}</code>\n",
            f"\U0001F4AC <b>WhatsApp service:</b> <code>{html.escape(str(cfg.get('service_whatsapp')))}</code>\n",
            f"\U0001F501 <b>Number-change service:</b> <code>{html.escape(str(cfg.get('service_numchange')))}</code>\n",
            f"\U0001F9E9 <b>All-OTP service:</b> <code>{html.escape(str(cfg.get('service_allotp')))}</code>\n",
            f"\U0001F4E1 <b>Status:</b> {status_txt}\n",
            "\n<i>This single key powers all three panels: WhatsApp Accounts, "
            "TG Number Change and All Apps OTP.</i></blockquote>",
        ]
        return "".join(lines)

    def _otp_buttons():
        return [
            [style_btn("\U0001F511 Change API Key", "adm_otp_key", "success", icon=5796209712009581332)],
            [style_btn("\U0001F310 Change Base URL", "adm_otp_base", "primary", icon=5409098988156629257)],
            [style_btn("\U0001F9EA Test Connection", "adm_otp_test", "success", icon=5409098988156629257)],
            [style_btn("\u267B\ufe0f Reset to ENV", "adm_otp_reset", "danger", icon=5408832111773757273)],
            [style_btn("\U0001F519 Back", "adm_adminmain", "danger", icon=6129812419028982717)],
        ]

    @bot.on(events.CallbackQuery(pattern=r"^adm_otp$"))
    async def cb_adm_otp(e):
        if not is_admin(e.sender_id):
            return
        text = await _otp_panel_text()
        try:
            await e.edit(text, buttons=_otp_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_otp_key$"))
    async def cb_adm_otp_key(e):
        if not is_admin(e.sender_id):
            return
        from utils import runtime_config
        chat = e.chat_id
        await e.answer()
        async with bot.conversation(chat, timeout=300) as conv:
            await conv.send_message(
                "<blockquote>\U0001F511 <b>Send the TemporaSMS API key</b>\n\n"
                "Dashboard \u2192 API \u2192 copy the key.\n"
                "It powers WhatsApp Accounts, TG Number Change and All Apps OTP.\n\n"
                "<i>Type /cancel to abort.</i></blockquote>")
            resp = await conv.get_response()
            raw = (resp.text or "").strip()
            if raw.lower() in ("/cancel", "cancel"):
                await conv.send_message("\u2139\ufe0f Cancelled \u2014 nothing changed.")
            elif len(raw) < 8:
                await conv.send_message("\u274c That looks too short for an API key. Nothing changed.")
            else:
                runtime_config.set("temporasms_api_key", raw)
                await conv.send_message("\u2705 TemporaSMS key updated. The three OTP panels "
                                        "will use it immediately.")
        text = await _otp_panel_text()
        try:
            await e.edit(text, buttons=_otp_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_otp_base$"))
    async def cb_adm_otp_base(e):
        if not is_admin(e.sender_id):
            return
        from utils import runtime_config
        chat = e.chat_id
        await e.answer()
        async with bot.conversation(chat, timeout=300) as conv:
            await conv.send_message(
                "<blockquote>\U0001F310 <b>Send the TemporaSMS base URL</b>\n\n"
                "Default: <code>https://api.temporasms.com</code>\n\n"
                "<i>Type /cancel to abort.</i></blockquote>")
            resp = await conv.get_response()
            raw = (resp.text or "").strip()
            if raw.lower() in ("/cancel", "cancel"):
                await conv.send_message("\u2139\ufe0f Cancelled \u2014 nothing changed.")
            elif not raw.startswith("http"):
                await conv.send_message("\u274c The URL must start with http:// or https://")
            else:
                runtime_config.set("temporasms_base_url", raw)
                await conv.send_message("\u2705 Base URL updated.")
        text = await _otp_panel_text()
        try:
            await e.edit(text, buttons=_otp_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_otp_reset$"))
    async def cb_adm_otp_reset(e):
        if not is_admin(e.sender_id):
            return
        from utils import runtime_config
        for key in ("temporasms_api_key", "temporasms_base_url",
                    "temporasms_service_whatsapp", "temporasms_service_numchange",
                    "temporasms_service_allotp"):
            runtime_config.clear(key)
        await e.answer("Reset to environment values", alert=False)
        text = await _otp_panel_text()
        try:
            await e.edit(text, buttons=_otp_buttons())
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_otp_test$"))
    async def cb_adm_otp_test(e):
        if not is_admin(e.sender_id):
            return
        from utils import temporasms
        try:
            ok, msg = await temporasms.check_connection()
            body = msg if isinstance(msg, str) else str(msg)
            mark = "\u2705" if ok else "\u274c"
            text = f"<blockquote>{mark} {body[:900]}</blockquote>"
        except Exception as ex:
            text = f"<blockquote>\u274c <b>Test failed</b>\n\n{html.escape(str(ex)[:300])}</blockquote>"
        btns = [[style_btn("\U0001F519 Back", "adm_otp", "danger", icon=6129812419028982717)]]
        try:
            await e.edit(text, buttons=btns)
        except Exception:
            pass

    @bot.on(events.NewMessage(pattern=r"(?i)^/(?:lztmargin|setlztmargin)(?:@\w+)?(?:\s+(\S+))?\s*$"))
    async def lzt_margin_command(e):
        if not is_admin(e.sender_id):
            return

        amount_text = e.pattern_match.group(1)
        if amount_text is None:
            return await e.reply(
                f"Current LZT markup: ₹{get_lzt_margin():g} per item.\n"
                "Usage: /lztmargin 25"
            )

        try:
            set_lzt_margin(float(amount_text))
        except (TypeError, ValueError, OverflowError):
            return await e.reply(
                "Enter a finite, non-negative INR amount. Example: /lztmargin 25"
            )

        return await e.reply(
            f"✅ LZT markup set to ₹{get_lzt_margin():g} per item."
        )
