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
from config import PE_CROWN, PE_CHECK, PE_GIFT, PE_LOCATION, PE_LIGHTNING, P_USERS, P_PKG, P_WAIT, P_ON, P_YES, P_NO, P_WARN, P_DOC, P_FLAG, P_MONEY, P_PHONE, P_GLOBE, P_2FA, P_CAL, P_OTP, P_CARD, P_TG, P_ACC, P_USDT, P_UPI, P_CART, P_GIFT, P_STATS, P_OFF, API_ID, API_HASH, bot, is_super_admin
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
        r3.append(style_btn("User Info", "adm_userinfo", "primary", icon=5409098988156629257))
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
        btns.append([style_btn("📧 Temp Mail (API)", "adm_tempmail", "primary", icon=5796209712009581332)])
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
              f"{P_MONEY} <b>\U0001d40f\u0280\u1d0f\u0493\u026a\u1d1b:</b> {_profit_rule}\n"
              f"{P_USDT} <b>1 USDT:</b> \u20b9{_usdt_rate:g}\n"
              f"{P_STATS} <b>\U0001d40f\u0280\u1d0f\u0493\u026a\u1d1b \u1d07\u1d00\u0280\u0274\u1d07\u1d05:</b> \u20b9{_earned:,.0f}\n"
              f"{PE_GIFT} <b>\U0001d40e\u1d21\u0274\u1d07\u0280 \U0001d408\U0001d403:</b> <code>{ADMIN_ID}</code>"
              + (f"\n{PE_CROWN} <b>\U0001d412\u1d1c\u1d18\u1d07\u0280 \U0001d400\u1d05\u1d0d\u026a\u0274 \U0001d408\U0001d403:</b> <code>{uid}</code>" if is_super_admin(uid) else "")
              + "</blockquote>")
    try: await event.edit(header, buttons=btns)
    except: await bot.send_message(event.chat_id, header, buttons=btns)

def register_admin(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^([/!]?admin|🔐 𝐀ᴅᴍɪɴ 𝐏ᴀɴᴇʟ|🔐 Admin Panel)$"))
    async def msg_admin(e):
        await admin_panel_handler(e)

    @bot.on(events.CallbackQuery(pattern=r"^adm_tempmail$"))
    async def cb_adm_tempmail(e):
        if not is_admin(e.sender_id):
            return
        from config import TEMPMAIL_API_KEY, TEMPMAIL_BASE_URL
        from utils import tempmail as tm
        status = "🟢 Configured" if TEMPMAIL_API_KEY else "🔴 Missing key"
        domains = []
        err = None
        try:
            domains = await tm.get_domains(use_cache=False)
        except Exception as ex:
            err = str(ex)
        lines = [
            "<blockquote expandable>📧 <b>Temp Mail (MTempMail API)</b>\n\n",
            f"🔑 <b>Status:</b> {status}\n",
            f"🌐 <b>Base URL:</b> <code>{html.escape(TEMPMAIL_BASE_URL)}</code>\n",
            f"🗂 <b>Domains:</b> {len(domains)}\n",
        ]
        if domains:
            lines.append("\n<b>Available domains:</b>\n")
            for d in domains[:8]:
                lines.append(f"• <code>{html.escape(d['domain'])}</code> <i>({html.escape(d['type'])})</i>\n")
        if err:
            lines.append(f"\n⚠️ <b>Last error:</b> {html.escape(err)}\n")
        lines.append("\nUsers open it from the main menu → <b>Free Temp Mail</b>.</blockquote>")
        btns = [
            [style_btn("🧪 Test Create Inbox", "adm_tm_test", "success", icon=5796209712009581332)],
            [style_btn("🔙 Back", "adm_adminmain", "danger", icon=6129812419028982717)],
        ]
        try:
            await e.edit("".join(lines), buttons=btns)
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=r"^adm_tm_test$"))
    async def cb_adm_tm_test(e):
        if not is_admin(e.sender_id):
            return
        from utils import tempmail as tm
        try:
            data = await tm.create_email()
            email = data.get("email")
            text = (f"<blockquote>✅ <b>Temp Mail works!</b>\n\n"
                    f"📧 <code>{html.escape(str(email))}</code>\n"
                    f"⏳ Expires: {html.escape(str(data.get('expire_at') or 'n/a'))}</blockquote>")
        except Exception as ex:
            text = f"<blockquote>❌ <b>Temp Mail test failed</b>\n\n{html.escape(str(ex))}</blockquote>"
        btns = [[style_btn("🔙 Back", "adm_tempmail", "danger", icon=6129812419028982717)]]
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
