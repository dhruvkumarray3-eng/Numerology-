import os
import re
import time
import asyncio
import csv
import zipfile
import shutil
import html
from telethon import events, Button, TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, UserIsBlockedError, InputUserDeactivatedError
from telethon.tl.functions.account import GetPasswordRequest
from database import (
    cur, db, is_admin, has_perm, ADMIN_ID, get_usdt_rate, COUNTRY_CODES,
    get_flag_by_country_name, get_country_info, update_balance, is_bot_online,
    get_bot_mode, set_bot_mode, get_lzt_key, set_lzt_key, get_rub_rate,
    set_rub_rate, get_lzt_margin, set_lzt_margin, get_fsub_status, set_fsub_status,
    get_fsub_channels, get_fsub_urls, set_fsub_data, add_fsub_channel,
    remove_fsub_channel, get_log_channels_db, set_log_channels_db,
    add_log_channel_db, remove_log_channel_db, get_change_number_fee,
    set_change_number_fee
)
from config import *
from utils.keyboards import style_btn
from utils.states import admin_state
from utils.lzt import lzt_client, validate_token_format, token_fingerprint
from plugins.admin import admin_panel_handler

try:
    from utils import search_settings as ss
except Exception:  # pragma: no cover - defensive
    ss = None


async def render_search_settings(event):
    """Admin page: every knob that controls live search & Good/Cheap stock."""
    if ss is None:
        return await event.edit(
            "<blockquote>⚠️ Search settings module is unavailable.</blockquote>",
            buttons=[[style_btn("🔙 Back", "adm_adminmain", "danger",
                                icon=6129888444245089008)]],
        )

    cfg = ss.get_search_settings()
    on = "🟢 ON"
    off = "🔴 OFF"

    def flt(key):
        val = cfg.get(key, "")
        return ss.FILTER_LABELS.get(val, val or "—")

    def ordr(key):
        val = cfg.get(key, "")
        return ss.ORDER_LABELS.get(val, val or "—")

    live = on if cfg.get("live_search_enabled") == "1" else off
    both = on if cfg.get("both_cheap") == "1" else off
    strict = on if cfg.get("strict_spam") == "1" else off
    zero = on if cfg.get("show_zero_counts") == "1" else off
    geospam = on if cfg.get("allow_geo_spam") == "1" else off
    fallback = on if cfg.get("auto_fallback") == "1" else off

    minp = cfg.get("min_price") or "no limit"
    maxp = cfg.get("max_price") or "no limit"

    msg = (
        "<blockquote>⚙️ <b>𝕊𝕖𝕒𝕣𝕔𝕙 & ℚ𝕦𝕒𝕝𝕚𝕥𝕪 𝕊𝕖𝕥𝕥𝕚𝕟𝕘𝕤</b>\n\n"
        f"📡 <b>Live Market Search:</b> {live}\n"
        f"🟢 <b>Good Quality Filter:</b> {flt('good_filter')}\n"
        f"💰 <b>Cheap Filter:</b> {flt('cheap_filter')}\n"
        f"🔁 <b>Both buttons show cheap:</b> {both}\n"
        f"↕️ <b>Good Sort:</b> {ordr('good_order')}\n"
        f"↕️ <b>Cheap Sort:</b> {ordr('cheap_order')}\n"
        f"↕️ <b>All / Bulk Sort:</b> {ordr('bulk_order')}\n"
        f"📦 <b>Max Results:</b> {cfg.get('max_results')}\n"
        f"📄 <b>Max Pages:</b> {cfg.get('max_pages')}\n"
        f"💵 <b>Min Price (RUB):</b> {minp}\n"
        f"💵 <b>Max Price (RUB):</b> {maxp}\n"
        f"🛡 <b>Strict Spam Check:</b> {strict}\n"
        f"🔢 <b>Show (0) counts:</b> {zero}\n"
        f"🌐 <b>Allow Geo-Spam (spam=no):</b> {geospam}\n"
        f"🔁 <b>Auto-Fallback on empty:</b> {fallback}\n\n"
        "<i>Tip: turn ON “Both buttons show cheap” to make Good Quality "
        "and Cheap both return the cheapest spam-blocked stock.</i></blockquote>"
    )

    btns = [
        [style_btn(f"📡 Live Search: {live}", "adm_ss_toggle|live_search_enabled",
                   "success" if cfg.get("live_search_enabled") == "1" else "danger",
                   icon=5409320020058584473),
         style_btn(f"🔁 Both Cheap: {both}", "adm_ss_toggle|both_cheap",
                   "success" if cfg.get("both_cheap") == "1" else "danger",
                   icon=5409320020058584473)],
        [style_btn(f"🟢 Good: {flt('good_filter')}", "adm_ss_cycle|good_filter",
                   "primary", icon=5409098988156629257),
         style_btn(f"💰 Cheap: {flt('cheap_filter')}", "adm_ss_cycle|cheap_filter",
                   "primary", icon=5409098988156629257)],
        [style_btn(f"↕️ Good Sort: {ordr('good_order')}", "adm_ss_cycle|good_order",
                   "primary", icon=5409098988156629257),
         style_btn(f"↕️ Cheap Sort: {ordr('cheap_order')}", "adm_ss_cycle|cheap_order",
                   "primary", icon=5409098988156629257)],
        [style_btn(f"↕️ Bulk Sort: {ordr('bulk_order')}", "adm_ss_cycle|bulk_order",
                   "primary", icon=5409098988156629257),
         style_btn(f"📦 Results: {cfg.get('max_results')}", "adm_ss_cycle|max_results",
                   "primary", icon=5409098988156629257)],
        [style_btn(f"📄 Pages: {cfg.get('max_pages')}", "adm_ss_cycle|max_pages",
                   "primary", icon=5409098988156629257),
         style_btn(f"🛡 Strict Spam: {strict}", "adm_ss_toggle|strict_spam",
                   "success" if cfg.get("strict_spam") == "1" else "danger",
                   icon=5409320020058584473)],
        [style_btn(f"💵 Min: {minp}", "adm_ss_price|min_price", "primary",
                   icon=5409098988156629257),
         style_btn(f"💵 Max: {maxp}", "adm_ss_price|max_price", "primary",
                   icon=5409098988156629257)],
        [style_btn(f"🌐 Geo-Spam: {geospam}", "adm_ss_toggle|allow_geo_spam",
                   "success" if cfg.get("allow_geo_spam") == "1" else "danger",
                   icon=5409320020058584473),
         style_btn(f"🔁 Auto-Fallback: {fallback}", "adm_ss_toggle|auto_fallback",
                   "success" if cfg.get("auto_fallback") == "1" else "danger",
                   icon=5409320020058584473)],
        [style_btn(f"🔢 Show (0): {zero}", "adm_ss_toggle|show_zero_counts",
                   "success" if cfg.get("show_zero_counts") == "1" else "danger",
                   icon=5409320020058584473),
         style_btn("♻️ Reset Defaults", "adm_ss_reset", "danger",
                   icon=6129888444245089008)],
        [style_btn("🌐 LZT Panel Settings", "adm_lzt_settings", "primary",
                   icon=5409166771330494453),
         style_btn("🔙 Back to Admin", "adm_adminmain", "danger",
                   icon=6129888444245089008)],
    ]
    return await event.edit(msg, buttons=btns)


async def channels_manager_menu(event):
    fsub_status = get_fsub_status()
    fsub_btn_text = "🟢 FSub: ON" if fsub_status == 'on' else "🔴 FSub: OFF"
    
    check_channels = get_fsub_channels()
    join_urls = get_fsub_urls()
    log_channels = get_log_channels_db()
    
    fsub_list_str = ""
    for i, ch in enumerate(check_channels):
        url = join_urls[i] if i < len(join_urls) else "No link"
        fsub_list_str += f"  • <code>{ch}</code> ➡️ {url}\n"
    if not fsub_list_str: fsub_list_str = "  <i>No Must-Join channels configured.</i>\n"

    log_list_str = ""
    for ch in log_channels:
        log_list_str += f"  • <code>{ch}</code>\n"
    if not log_list_str: log_list_str = "  <i>No Log channels configured.</i>\n"

    msg = (f"<blockquote>📢 <b>𝐂ʜᴀɴɴᴇʟs & 𝐅𝐒ᴜʙ 𝐌ᴀɴᴀɢᴇʀ</b>\n\n"
           f"🛡️ <b>𝐅ᴏʀᴄᴇ 𝐒ᴜʙsᴄʀɪʙᴇ:</b> <b>{fsub_status.upper()}</b>\n"
           f"{fsub_list_str}\n"
           f"📝 <b>𝐋ᴏɢ / 𝐀ᴘᴘʀᴏᴠᴀʟ 𝐂ʜᴀɴɴᴇʟs:</b>\n"
           f"{log_list_str}</blockquote>")

    btns = [
        [style_btn(fsub_btn_text, "adm_toggle_fsub", "primary", icon=5409098988156629257)],
        [style_btn("➕ Add Must-Join Ch", "adm_add_fsub", "success", icon=5409271925014801629),
         style_btn("🗑️ Remove Must-Join", "adm_rem_fsub", "danger", icon=5408832111773757273)],
        [style_btn("➕ Add Log Channel", "adm_add_logch", "success", icon=5409271925014801629),
         style_btn("🗑️ Remove Log Ch", "adm_rem_logch", "danger", icon=5408832111773757273)],
        [style_btn("🔄 Set All FSub Data", "adm_set_all_fsub", "primary", icon=5409098988156629257)],
        [style_btn("🔙 Back to Admin", "adm_adminmain", "danger", icon=6129812419028982717)]
    ]
    try: await event.edit(msg, buttons=btns)
    except: await bot.send_message(event.chat_id, msg, buttons=btns)

async def run_stock_check(event):
    msg = await event.respond("🔄 <b>Checking Stock...</b>\nPlease wait, this may take a while.", parse_mode="html")
    stock_items = cur.execute("SELECT phone, session_file FROM stock WHERE available=1").fetchall()
    total = len(stock_items)
    if total == 0:
        return await msg.edit("⚠️ <b>No stock to check.</b>", parse_mode="html")
    
    dead = 0
    alive = 0
    for idx, (phone, sess) in enumerate(stock_items):
        try:
            client = TelegramClient(sess, API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Dead")
            alive += 1
        except Exception:
            dead += 1
            cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
            db.commit()
        finally:
            try: await client.disconnect()
            except: pass
        
        if (idx + 1) % 5 == 0:
            try: await msg.edit(f"🔄 <b>Checking Stock...</b> {idx+1}/{total}\n✅ Alive: {alive}\n❌ Dead: {dead}", parse_mode="html")
            except: pass
            
    await msg.edit(f"✅ <b>Stock Check Complete!</b>\n\nTotal Checked: {total}\n✅ Alive: {alive}\n❌ Dead (Removed): {dead}", parse_mode="html")

async def detect_account_year(client):
    """Detect account creation year from earliest dialog/message."""
    try:
        me = await client.get_me()
        # Try using the user's own ID creation date approximation
        # Get the earliest message in Saved Messages
        async for msg in client.iter_messages('me', limit=1, reverse=True):
            if msg.date:
                return msg.date.year
        # Fallback: check earliest dialog
        async for dialog in client.iter_dialogs(limit=5):
            if dialog.date:
                return dialog.date.year
    except Exception:
        pass
    from datetime import datetime
    return datetime.now().year

async def manage_admins_menu(event):
    rows = cur.execute("SELECT user_id FROM admins").fetchall()
    msg = f"{PE_CROWN} <b>Manage Sub-Admins</b>\n\n"
    for r in rows: msg += f"{P_ACC} <code>{r[0]}</code>\n"
    btns = [[style_btn("Add Admin", "adm_addadmin", "primary", icon=5409098988156629257), style_btn("Edit Admin", "adm_editadminreq", "primary", icon=5409098988156629257)],
            [style_btn("Back", "adm_adminmain", "danger", icon=6129888444245089008)]]
    await event.edit(msg, buttons=btns)

async def edit_admin_menu(event, target_id):
    row = cur.execute("SELECT p_add_stock, p_manage_stock, p_stats, p_bal, p_settings FROM admins WHERE user_id=?", (target_id,)).fetchone()
    if not row: return await event.answer("Admin not found", alert=True)
    p = ["✅" if x==1 else "❌" for x in row]
    
    btns = [
        [style_btn(f"Add Stock: {p[0]}", f"adm_tglperm|{target_id}|p_add_stock", "primary", icon=5409098988156629257)],
        [style_btn(f"Manage Stock: {p[1]}", f"adm_tglperm|{target_id}|p_manage_stock", "primary", icon=5409098988156629257)],
        [style_btn(f"Stats & Bcast: {p[2]}", f"adm_tglperm|{target_id}|p_stats", "primary", icon=5409098988156629257)],
        [style_btn(f"Bal & Users: {p[3]}", f"adm_tglperm|{target_id}|p_bal", "primary", icon=5409098988156629257)],
        [style_btn(f"Settings: {p[4]}", f"adm_tglperm|{target_id}|p_settings", "primary", icon=5409098988156629257)],
        [style_btn("Remove Admin", f"adm_deladmin|{target_id}", "danger", icon=6129888444245089008)],
        [style_btn("Back", "adm_manageadmins", "danger", icon=6129888444245089008)]
    ]
    await event.edit(f"✏️ <b>Editing Admin:</b> <code>{target_id}</code>", buttons=btns)

async def send_manage_stock_page(event, page):
    limit = 10
    offset = (page - 1) * limit
    rows = cur.execute("SELECT DISTINCT country_name FROM stock ORDER BY country_name").fetchall()
    total = len(rows)
    countries = rows[offset:offset+limit]
    
    btns = []
    for (c,) in countries: 
        flag = get_flag_by_country_name(c)
        btns.append([style_btn(f"{flag} {c}", f"adm_msc|{c}", "primary", icon=5409098988156629257)])
    
    nav = []
    if page > 1: nav.append(style_btn("Prev", f"adm_mspg|{page-1}", "primary", icon=5409098988156629257))
    if offset + limit < total: nav.append(style_btn("Next", f"adm_mspg|{page+1}", "primary", icon=5409098988156629257))
    if nav: btns.append(nav)
    btns.append([style_btn("Back", "adm_adminmain", "danger", icon=6129888444245089008)])
    await event.edit(f"{PE_LOCATION} <b>Manage Stock</b> (Page {page})\nSelect a country to edit its properties:", buttons=btns)

async def send_manage_stock_country(event, c_name):
    years = cur.execute("SELECT DISTINCT account_year FROM stock WHERE country_name=? ORDER BY account_year DESC", (c_name,)).fetchall()
    flag = get_flag_by_country_name(c_name)
    btns = [
        [style_btn("Edit Country Name", f"adm_msedit|name|{c_name}", "primary", icon=5409098988156629257), style_btn("Edit Flag", f"adm_msedit|flag|{c_name}", "primary", icon=5409098988156629257)],
        [style_btn("Edit Common Price (All Years)", f"adm_msedit|cprice|{c_name}", "primary", icon=5409098988156629257)]
    ]
    y_btns = []
    for (y,) in years: y_btns.append(style_btn(f"{y}", f"adm_msedit|yprice|{c_name}|{y}", "primary", icon=5409098988156629257))
    
    for i in range(0, len(y_btns), 3): btns.append(y_btns[i:i+3])
    btns.append([style_btn("Back", "adm_mspg|1", "danger", icon=6129888444245089008)])
    await event.edit(f"{flag} <b>Managing: {c_name}</b>\nSelect an option to edit:", buttons=btns)

async def send_autoprice_page(event, page):
    limit = 10
    offset = (page - 1) * limit
    c_list = set([c[0] for c in COUNTRY_CODES.values()])
    db_countries = cur.execute("SELECT DISTINCT country_name FROM stock").fetchall()
    for (c,) in db_countries: c_list.add(c)
    
    custom_countries = cur.execute("SELECT DISTINCT name FROM custom_countries").fetchall()
    for (c,) in custom_countries: c_list.add(c)

    c_list = sorted(list(c_list))
    total = len(c_list)
    countries = c_list[offset:offset+limit]
    
    btns = []
    for c in countries: 
        flag = get_flag_by_country_name(c)
        btns.append([style_btn(f"{flag} {c}", f"adm_apc|{c}", "primary", icon=5409098988156629257)])
        
    nav = []
    if page > 1: nav.append(style_btn("Prev", f"adm_appg|{page-1}", "primary", icon=5409098988156629257))
    if offset + limit < total: nav.append(style_btn("Next", f"adm_appg|{page+1}", "primary", icon=5409098988156629257))
    if nav: btns.append(nav)
    btns.append([style_btn("Add Custom Country", "adm_ap_add_country", "primary", icon=5409098988156629257)])
    btns.append([style_btn("Back", "adm_adminmain", "danger", icon=6129888444245089008)])
    await event.edit(f"{PE_LIGHTNING} <b>Auto Price Setup</b> (Page {page})\nSelect a country to set fixed prices:", buttons=btns)

async def send_autoprice_country(event, c_name):
    flag = get_flag_by_country_name(c_name)
    btns = [[style_btn("Set Common Price (All Years)", f"adm_apset|{c_name}|Common", "primary", icon=5409098988156629257)]]
    y_btns = []
    for y in range(2026, 2017, -1): y_btns.append(style_btn(f"{y}", f"adm_apset|{c_name}|{y}", "primary", icon=5409098988156629257))
    for i in range(0, len(y_btns), 3): btns.append(y_btns[i:i+3])
    btns.append([style_btn("Back", "adm_appg|1", "danger", icon=6129888444245089008)])
    await event.edit(f"{flag} <b>Auto Price: {c_name}</b>\nSelect 'Common' for default price, or a specific year:", buttons=btns)

async def admin_actions(event):
    data_full = event.data.decode()
    if not data_full.startswith("adm_"): return
    uid = event.sender_id
    action_data = data_full[4:]
    chat = event.chat_id
    
    if action_data == "adminmain":
        await event.delete()
        class FakeEvent: chat_id = chat; sender_id = uid
        return await admin_panel_handler(FakeEvent())

    if action_data == "servers" and has_perm(uid, 'p_settings'):
        from plugins.servers import parse_servers
        servers = parse_servers()
        lines = ["<blockquote>\U0001F5A5 <b>Server Switches</b>\n"]
        btns = []
        for idx, srv in enumerate(servers, start=1):
            is_on = srv["status"] == "on"
            state = "\U0001F7E2 ON" if is_on else "\U0001F534 OFF"
            btn_state = "ON \U0001F7E2" if is_on else "OFF \U0001F534"
            lines.append(f"<b>{idx}. {html.escape(srv['name'])}</b> \u2014 {state}")
            btns.append([style_btn(
                f"{idx}. {srv['name']}  \u2014  {btn_state}",
                f"adm_srvtoggle|{idx}",
                "success" if is_on else "danger",
            )])
        lines.append("\n<i>Tap a server to flip it ON/OFF. Changes apply instantly.</i></blockquote>")
        btns.append([style_btn("\U0001F519 Back", "adm_adminmain", "danger", icon=6129888444245089008)])
        try:
            return await event.edit("\n".join(lines), buttons=btns)
        except Exception:
            return await bot.send_message(chat, "\n".join(lines), buttons=btns)

    if action_data.startswith("srvtoggle|") and has_perm(uid, 'p_settings'):
        try:
            idx = int(action_data.split("|", 1)[1])
        except (IndexError, ValueError):
            return await event.answer("Invalid server.", alert=True)
        from plugins.servers import parse_servers, set_server_status
        servers = parse_servers()
        if idx < 1 or idx > len(servers):
            return await event.answer("Invalid server.", alert=True)
        cur_state = servers[idx - 1]["status"]
        new_state = "off" if cur_state == "on" else "on"
        set_server_status(idx, new_state)
        answer_state = "ON \U0001F7E2" if new_state == "on" else "OFF \U0001F534"
        await event.answer(f"Server {idx} is now {answer_state}", alert=True)
        # Re-render the servers screen.
        class FakeEvent:
            chat_id = chat
            sender_id = uid
            data = b"adm_servers"
            async def edit(self, msg, buttons=None):
                try:
                    await event.edit(msg, buttons=buttons)
                except Exception:
                    pass
            async def answer(self, *a, **k):
                pass
        return await admin_actions(FakeEvent())

    if action_data.startswith("togglesmm|") and has_perm(uid, 'p_settings'):
        try:
            srv_id = int(action_data.split("|", 1)[1])
        except (IndexError, ValueError):
            return await event.answer("Invalid server.", alert=True)
        from utils.smm_client import toggle_server, is_server_enabled
        new_state = toggle_server(srv_id)
        state_text = "ON \U0001F7E2" if new_state else "OFF \U0001F534"
        await event.answer(f"SMM Server {srv_id} is now {state_text}", alert=True)
        class FakeEvent: chat_id = chat; sender_id = uid
        await admin_panel_handler(FakeEvent())
        try:
            await event.delete()
        except Exception:
            pass
        return

    if action_data == "togglebot" and has_perm(uid, 'p_settings'):
        new_status = 'off' if is_bot_online() else 'on'
        cur.execute("UPDATE settings SET value=? WHERE key='bot_status'", (new_status,))
        db.commit()
        await event.answer(f"Bot turned {new_status.upper()}", alert=True)
        class FakeEvent: chat_id = chat; sender_id = uid
        await admin_panel_handler(FakeEvent())
        await event.delete()
        return

    elif action_data == "toggle_mode" and has_perm(uid, 'p_settings'):
        curr = get_bot_mode()
        nxt = 'panel' if curr == 'manual' else ('hybrid' if curr == 'panel' else 'manual')
        set_bot_mode(nxt)
        mode_names = {'manual': '📂 Manual Mode', 'panel': '🌐 Panel (LZT) Mode', 'hybrid': '⚡ Hybrid Mode'}
        await event.answer(f"Switched to {mode_names[nxt]}", alert=True)
        class FakeEvent: chat_id = chat; sender_id = uid
        await admin_panel_handler(FakeEvent())
        await event.delete()
        return

    elif action_data == "search_settings" and has_perm(uid, 'p_settings'):
        return await render_search_settings(event)

    elif action_data.startswith("ss_toggle|") and has_perm(uid, 'p_settings'):
        key = action_data.split("|", 1)[1]
        if ss and key in ss._BOOL_KEYS:
            cur_val = ss.get_search_setting(key)
            try:
                ss.set_search_setting(key, "0" if cur_val == "1" else "1")
                await event.answer("Updated ✅", alert=False)
            except Exception as exc:
                await event.answer(f"Failed: {exc}", alert=True)
        return await render_search_settings(event)

    elif action_data.startswith("ss_cycle|") and has_perm(uid, 'p_settings'):
        key = action_data.split("|", 1)[1]
        if ss:
            choices = {
                "good_filter": ss.VALID_FILTERS,
                "cheap_filter": ss.VALID_FILTERS,
                "good_order": ss.VALID_ORDERS,
                "cheap_order": ss.VALID_ORDERS,
                "bulk_order": ss.VALID_ORDERS,
                "max_results": ss.VALID_LIMITS,
                "max_pages": ss.VALID_PAGES,
            }.get(key, [])
            if choices:
                cur_val = ss.get_search_setting(key)
                try:
                    idx = choices.index(cur_val)
                except ValueError:
                    idx = -1
                try:
                    ss.set_search_setting(key, choices[(idx + 1) % len(choices)])
                    await event.answer("Updated ✅", alert=False)
                except Exception as exc:
                    await event.answer(f"Failed: {exc}", alert=True)
        return await render_search_settings(event)

    elif action_data.startswith("ss_price|") and has_perm(uid, 'p_settings'):
        key = action_data.split("|", 1)[1]
        if key not in ("min_price", "max_price"):
            return await render_search_settings(event)
        label = "Minimum" if key == "min_price" else "Maximum"
        await event.answer()
        try:
            await event.edit(
                f"<blockquote>💵 Send the <b>{label} price in RUB</b>.\n"
                "Send <code>0</code> or <code>off</code> to remove the limit.</blockquote>",
                buttons=[[style_btn("❌ Cancel", "adm_search_settings", "danger",
                                    icon=6129888444245089008)]],
            )
        except Exception:
            pass
        chat = event.chat_id
        try:
            async with bot.conversation(chat, timeout=300) as conv:
                reply = await conv.get_response()
                txt = (reply.raw_text or "").strip().lower()
                if txt in ("off", "0", "none", "clear", "no"):
                    ss.set_search_setting(key, "")
                else:
                    try:
                        val = float(txt.replace("₹", "").replace("rub", "").strip())
                        if val < 0:
                            raise ValueError
                        ss.set_search_setting(key, str(int(val)) if val == int(val) else str(val))
                    except Exception:
                        await reply.reply("⚠️ Invalid number — price limit unchanged.")
        except Exception as exc:
            logger.warning(f"search settings price input failed: {exc}")
        class FakeEvent: chat_id = chat; sender_id = uid
        try:
            await render_search_settings(FakeEvent())
        except Exception:
            pass
        return

    elif action_data == "ss_reset" and has_perm(uid, 'p_settings'):
        if ss:
            ss.reset_search_settings()
        await event.answer("Reset to defaults ♻️", alert=True)
        return await render_search_settings(event)

    elif action_data == "lzt_settings" and has_perm(uid, 'p_settings'):
        key = get_lzt_key()
        masked_key = token_fingerprint(key) if key else "Not Set ❌"
        rub = get_rub_rate()
        margin = get_lzt_margin()
        mode = get_bot_mode()
        try:
            from utils.markup import get_markup_config, describe_markup
            _mk_desc = describe_markup(get_markup_config())
        except Exception:
            _mk_desc = f"+₹{margin} per sale"
        
        msg = (f"<blockquote>🌐 <b>𝐋𝐙𝐓 𝐏ᴀɴᴇʟ 𝐒ᴇᴛᴛɪɴɢs</b>\n\n"
               f"⚡ <b>𝐁ᴏᴛ 𝐌ᴏᴅᴇ:</b> <code>{mode.upper()}</code>\n"
               f"🔑 <b>𝐋𝐙𝐓 𝐀𝐏𝐈 𝐊ᴇʏ:</b> <code>{masked_key}</code>\n"
               f"💹 <b>𝐑𝐔𝐁 𝐭𝐨 𝐈𝐍𝐑 𝐑ᴀᴛᴇ:</b> ₹{rub}\n"
               f"💰 <b>𝐏ʀᴏғɪᴛ 𝐌ᴀʀɢɪɴ (𝐈𝐍𝐑):</b> {_mk_desc}\n\n"
               f"<i>💡 In Panel/Hybrid mode, stock is fetched from LZT Market in real-time.</i></blockquote>")
               
        btns = [
            [style_btn("🔑 Set API Key", "adm_setlztkey", "primary", icon=5409098988156629257),
             style_btn("📊 Test / Balance", "adm_lzttest", "success", icon=5409320020058584473)],
            [style_btn("💹 Set RUB Rate", "adm_setrubrate", "primary", icon=5409098988156629257),
             style_btn("💰 Set Profit Margin", "adm_setlztmargin", "primary", icon=5409098988156629257)],
            [style_btn("📋 Custom Price List", "adm_autoprice", "primary", icon=5409098988156629257)],
            [style_btn("🔙 Back to Admin", "adm_adminmain", "danger", icon=6129888444245089008)]
        ]
        return await event.edit(msg, buttons=btns)
        
    elif action_data == "lzttest" and has_perm(uid, 'p_settings'):
        await event.answer("Connecting to LZT...", alert=False)
        ok, res_msg = await lzt_client.check_connection()

        # Also run a real market search so the admin can see whether live
        # accounts actually come back (and why not, if they don't).
        extra = ""
        try:
            items = await asyncio.wait_for(
                lzt_client.search_items("India", mode="nonspam", limit=5),
                timeout=35,
            )
            err = getattr(lzt_client, "last_error", None)
            kind = getattr(lzt_client, "last_error_kind", None)
            status = getattr(lzt_client, "last_status", None)
            total = getattr(lzt_client, "last_total", 0)
            kind_badge = {
                "auth": "\U0001F511 key invalid",
                "access": "\U0001F6A7 market access required",
                "rate": "\u23F1\uFE0F rate limited",
                "bad": "\u26A0\uFE0F bad parameters",
                "server": "\U0001F6A7 LZT server error",
            }.get(kind, "")
            if items:
                cheapest = min(float(it.get("price_rub") or 0) for it in items)
                extra = (f"\n\n\U0001F50E <b>Market Search Test (India):</b> "
                         f"\u2705 {len(items)} item(s) found \u2014 cheapest "
                         f"{cheapest:.0f} RUB\n"
                         f"<i>HTTP {status} \u00b7 totalItems={total}</i>")
            elif err:
                # A real failure (rate limit / auth / access / timeout) — show
                # the honest reason instead of a misleading "0 items".
                extra = ("\n\n\U0001F50E <b>Market Search Test (India):</b> "
                         f"\u26a0\ufe0f could not complete "
                         f"({kind_badge or 'error'})\n"
                         f"<i>{html.escape(str(err))}</i>\n"
                         f"<i>HTTP {status} \u00b7 totalItems={total}</i>")
            else:
                extra = ("\n\n\U0001F50E <b>Market Search Test (India):</b> "
                         "\u2139\ufe0f 0 non-spam items right now "
                         "(India may genuinely be out of stock \u2014 try "
                         "another country or mode).\n"
                         f"<i>HTTP {status} \u00B7 totalItems={total}</i>")
        except asyncio.TimeoutError:
            extra = ("\n\n\U0001F50E <b>Market Search Test:</b> "
                     "\u23f1\ufe0f timed out \u2014 LZT is slow right now, "
                     "please retry.")
        except Exception as exc:
            extra = (f"\n\n\U0001F50E <b>Market Search Test:</b> "
                     f"\u274c {html.escape(str(exc))}")

        btns = [[style_btn("\U0001F504 Test Again", "adm_lzttest", "success", icon=5409320020058584473)],
                [style_btn("\U0001F519 Back", "adm_lzt_settings", "danger", icon=6129888444245089008)]]
        return await event.edit(f"<blockquote>{res_msg}{extra}</blockquote>", buttons=btns)

    elif action_data == "upi" and has_perm(uid, 'p_settings'):
        upi_res = cur.execute("SELECT value FROM settings WHERE key='upi_id'").fetchone()
        active_upi = upi_res[0] if upi_res and upi_res[0] else "vinit-godara@fam"
        msg = (f"<blockquote>🏦 <b>ᴜᴘɪ ᴘᴀʏᴍᴇɴᴛ ꜱᴇᴛᴛɪɴɢꜱ</b>\n\n"
               f"🆔 <b>ᴄᴜʀʀᴇɴᴛ ᴜᴘɪ ɪᴅ:</b> <code>{active_upi}</code>\n\n"
               f"<i>💡 This UPI ID is shown to every user on the deposit screen. "
               f"Change it anytime — it updates instantly, no restart needed.</i></blockquote>")
        btns = [
            [style_btn("✏️ Change UPI ID", "adm_change_upi", "success", icon=5409098988156629257)],
            [style_btn("💳 Auto-UPI / IMAP", "adm_autoupi", "primary", icon=5409271925014801629)],
            [style_btn("🔙 Back to Admin", "adm_adminmain", "danger", icon=6129812419028982717)]
        ]
        return await event.edit(msg, buttons=btns)

    elif action_data == "autoupi" and has_perm(uid, 'p_settings'):
        dep_mode_res = cur.execute("SELECT value FROM settings WHERE key='deposit_mode'").fetchone()
        dep_mode = dep_mode_res[0] if dep_mode_res and dep_mode_res[0] else "auto"
        mode_label = "🟢 Auto (IMAP UTR)" if dep_mode == 'auto' else ("⚡ Hybrid (Auto + Fallback)" if dep_mode == 'hybrid' else "📂 Manual (Screenshots)")
        
        upi_res = cur.execute("SELECT value FROM settings WHERE key='upi_id'").fetchone()
        active_upi = upi_res[0] if upi_res and upi_res[0] else "vinit-godara@fam"
        
        gmail_res = cur.execute("SELECT value FROM settings WHERE key='gmail_user'").fetchone()
        active_gmail = gmail_res[0] if gmail_res and gmail_res[0] else "vinitgodaragodara3@gmail.com"
        
        msg = (f"<blockquote>💳 <b>𝐀ᴜᴛᴏ-𝐔𝐏𝐈 & 𝐈𝐌𝐀𝐏 𝐆ᴀᴛᴇᴡᴀʏ 𝐒ᴇᴛᴛɪɴɢs</b>\n\n"
               f"⚙️ <b>𝐃ᴇᴘᴏsɪᴛ 𝐌ᴏᴅᴇ:</b> <b>{mode_label}</b>\n"
               f"🆔 <b>𝐀ᴄᴛɪᴠᴇ 𝐔𝐏𝐈 𝐈𝐃:</b> <code>{active_upi}</code>\n"
               f"📧 <b>𝐆ᴍᴀɪʟ 𝐀ᴄᴄᴏᴜɴᴛ:</b> <code>{active_gmail}</code>\n"
               f"🔒 <b>𝐀ɴᴛɪ-𝐃ᴜᴘʟɪᴄᴀᴛᴇ 𝐔𝐓𝐑:</b> 🟢 <b>Active (100% Protected)</b>\n\n"
               f"<i>💡 In Auto/Hybrid mode, payments are verified in real-time from bank notification emails!</i></blockquote>")
               
        btns = [
            [style_btn(f"🔄 Mode: {dep_mode.capitalize()}", "adm_toggle_dep_mode", "success", icon=5409271925014801629)],
            [style_btn("✏️ Change UPI ID", "adm_change_upi", "primary", icon=5409098988156629257),
             style_btn("📧 Change Gmail", "adm_change_gmail", "primary", icon=5409098988156629257)],
            [style_btn("🧪 Test IMAP Connection", "adm_test_imap", "primary", icon=5409320020058584473)],
            [style_btn("🔙 Back to Admin", "adm_adminmain", "danger", icon=6129888444245089008)]
        ]
        return await event.edit(msg, buttons=btns)

    elif action_data == "toggle_dep_mode" and has_perm(uid, 'p_settings'):
        dep_mode_res = cur.execute("SELECT value FROM settings WHERE key='deposit_mode'").fetchone()
        curr = dep_mode_res[0] if dep_mode_res and dep_mode_res[0] else "auto"
        nxt = "hybrid" if curr == "auto" else ("manual" if curr == "hybrid" else "auto")
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('deposit_mode', ?)", (nxt,))
        db.commit()
        await event.answer(f"Deposit Mode switched to {nxt.upper()}!", alert=True)
        # re-render menu
        dep_mode = nxt
        mode_label = "🟢 Auto (IMAP UTR)" if dep_mode == 'auto' else ("⚡ Hybrid (Auto + Fallback)" if dep_mode == 'hybrid' else "📂 Manual (Screenshots)")
        upi_res = cur.execute("SELECT value FROM settings WHERE key='upi_id'").fetchone()
        active_upi = upi_res[0] if upi_res and upi_res[0] else "vinit-godara@fam"
        gmail_res = cur.execute("SELECT value FROM settings WHERE key='gmail_user'").fetchone()
        active_gmail = gmail_res[0] if gmail_res and gmail_res[0] else "vinitgodaragodara3@gmail.com"
        
        msg = (f"<blockquote>💳 <b>𝐀ᴜᴛᴏ-𝐔𝐏𝐈 & 𝐈𝐌𝐀𝐏 𝐆ᴀᴛᴇᴡᴀʏ 𝐒ᴇᴛᴛɪɴɢs</b>\n\n"
               f"⚙️ <b>𝐃ᴇᴘᴏsɪᴛ 𝐌ᴏᴅᴇ:</b> <b>{mode_label}</b>\n"
               f"🆔 <b>𝐀ᴄᴛɪᴠᴇ 𝐔𝐏𝐈 𝐈𝐃:</b> <code>{active_upi}</code>\n"
               f"📧 <b>𝐆ᴍᴀɪʟ 𝐀ᴄᴄᴏᴜɴᴛ:</b> <code>{active_gmail}</code>\n"
               f"🔒 <b>𝐀ɴᴛɪ-𝐃ᴜᴘʟɪᴄᴀᴛᴇ 𝐔𝐓𝐑:</b> 🟢 <b>Active (100% Protected)</b>\n\n"
               f"<i>💡 In Auto/Hybrid mode, payments are verified in real-time from bank notification emails!</i></blockquote>")
        btns = [
            [style_btn(f"🔄 Mode: {dep_mode.capitalize()}", "adm_toggle_dep_mode", "success", icon=5409271925014801629)],
            [style_btn("✏️ Change UPI ID", "adm_change_upi", "primary", icon=5409098988156629257),
             style_btn("📧 Change Gmail", "adm_change_gmail", "primary", icon=5409098988156629257)],
            [style_btn("🧪 Test IMAP Connection", "adm_test_imap", "primary", icon=5409320020058584473)],
            [style_btn("🔙 Back to Admin", "adm_adminmain", "danger", icon=6129888444245089008)]
        ]
        return await event.edit(msg, buttons=btns)

    elif action_data == "test_imap" and has_perm(uid, 'p_settings'):
        await event.answer("Testing IMAP...", alert=False)
        from utils.imap_verifier import get_imap_credentials
        u, p = get_imap_credentials()
        try:
            import ssl, imaplib
            context = ssl.create_default_context()
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=context)
            mail.login(u, p)
            mail.select("INBOX")
            status, data = mail.search(None, "ALL")
            total = len(data[0].split())
            mail.logout()
            await event.answer(f"✅ IMAP Connected!\n📧 {u}\nTotal Inbox Emails: {total}", alert=True)
        except Exception as imap_err:
            await event.answer(f"❌ IMAP Connection Failed: {imap_err}", alert=True)
        return

    elif action_data == "stats" and has_perm(uid, 'p_stats'):
        u_row = cur.execute("SELECT COUNT(*) FROM users").fetchone()
        u = u_row[0] if u_row else 0
        s_row = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()
        s = s_row[0] if s_row else 0
        r_row = cur.execute("SELECT value FROM settings WHERE key='upi_revenue'").fetchone()
        r = r_row[0] if r_row else "0"
        bal_row = cur.execute("SELECT SUM(balance) FROM users").fetchone()
        total_bal = bal_row[0] if bal_row and bal_row[0] else 0
        o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders").fetchone()
        total_orders = o_row[0] if o_row else 0
        total_spent = o_row[1] if o_row and o_row[1] else 0
        
        msg = (f"{P_STATS} <b>ADVANCED STATS</b>\n\n{P_USERS} <b>Total Users:</b> {u}\n{P_PKG} <b>Accounts in Stock:</b> {s}\n"
               f"{P_MONEY} <b>Total UPI Revenue:</b> {P_INR}{r}\n\n{P_CARD} <b>Overall Users Balance:</b> {P_INR}{total_bal}\n"
               f"{P_CART} <b>Total Accounts Sold:</b> {total_orders}\n{P_USDT} <b>Overall Sales Amount:</b> {P_INR}{total_spent}")
        return await event.edit(msg, buttons=[[style_btn("Back", "adm_adminmain", "danger", icon=6129888444245089008)]])

    elif action_data == "channels_mgr" and has_perm(uid, 'p_settings'):
        return await channels_manager_menu(event)

    elif action_data == "toggle_fsub" and has_perm(uid, 'p_settings'):
        curr = get_fsub_status()
        nxt = 'off' if curr == 'on' else 'on'
        set_fsub_status(nxt)
        await event.answer(f"Force Subscribe turned {nxt.upper()}!", alert=True)
        return await channels_manager_menu(event)

    elif action_data == "rem_fsub" and has_perm(uid, 'p_settings'):
        chs = get_fsub_channels()
        urls = get_fsub_urls()
        if not chs:
            await event.answer("⚠️ No Must-Join channels to remove.", alert=True)
            return await channels_manager_menu(event)
        btns = []
        for i, ch in enumerate(chs):
            url_text = f" ({urls[i]})" if i < len(urls) else ""
            btns.append([style_btn(f"🗑️ Delete #{i+1}: {ch}{url_text[:25]}", f"adm_delfsub|{i}", "danger", icon=5408832111773757273)])
        btns.append([style_btn("🔙 Back", "adm_channels_mgr", "danger", icon=6129812419028982717)])
        return await event.edit("<blockquote>🗑️ <b>Select Must-Join Channel to Remove:</b></blockquote>", buttons=btns)

    elif action_data.startswith("delfsub|") and has_perm(uid, 'p_settings'):
        idx = int(action_data.split("|")[1])
        remove_fsub_channel(idx)
        await event.answer("✅ Channel Removed from Must-Join!", alert=True)
        return await channels_manager_menu(event)

    elif action_data == "rem_logch" and has_perm(uid, 'p_settings'):
        chs = get_log_channels_db()
        if not chs:
            await event.answer("⚠️ No Log channels to remove.", alert=True)
            return await channels_manager_menu(event)
        btns = []
        for ch in chs:
            btns.append([style_btn(f"🗑️ Delete Log: {ch}", f"adm_dellogch|{ch}", "danger", icon=5408832111773757273)])
        btns.append([style_btn("🔙 Back", "adm_channels_mgr", "danger", icon=6129812419028982717)])
        return await event.edit("<blockquote>🗑️ <b>Select Log Channel to Remove:</b></blockquote>", buttons=btns)

    elif action_data.startswith("dellogch|") and has_perm(uid, 'p_settings'):
        ch = action_data.split("|")[1]
        remove_log_channel_db(ch)
        await event.answer(f"✅ Log Channel {ch} Removed!", alert=True)
        return await channels_manager_menu(event)

    elif action_data == "payments" and has_perm(uid, 'p_settings'):
        btns = [
            [style_btn("Add Payment Method", "adm_addpay", "primary", icon=5409098988156629257)],
            [style_btn("Remove Payment Method", "adm_delpay", "danger", icon=6129888444245089008)],
            [style_btn("Back to Admin", "adm_adminmain", "danger", icon=6129888444245089008)]
        ]
        return await event.edit(f"{P_CARD} <b>Manage Payment Methods</b>", buttons=btns)

    elif action_data == "trustwallet" and has_perm(uid, 'p_settings'):
        from database import get_trust_wallet_address, get_trust_wallet_qr
        addr = get_trust_wallet_address() or "not set"
        qr = get_trust_wallet_qr() or "auto-generated from address"
        msg = (f"<blockquote>\U0001F4B0 <b>Trust Wallet / USDT (BEP-20)</b>\n\n"
               f"\U0001F45B <b>Address:</b> <code>{html.escape(addr)}</code>\n"
               f"\U0001F5BC <b>QR:</b> {html.escape(qr)}\n\n"
               f"<i>These values are used for every USDT deposit and can be changed "
               f"here anytime. Leave the QR empty to auto-generate one.</i></blockquote>")
        btns = [
            [style_btn("\u270F\uFE0F Change Address", "adm_walletaddr", "primary", icon=5409098988156629257)],
            [style_btn("\U0001F5BC Change QR (photo / URL)", "adm_walletqr", "success", icon=5409320020058584473)],
            [style_btn("\U0001F5D1 Remove QR (auto QR)", "adm_walletqr_clear", "danger", icon=6129888444245089008)],
            [style_btn("\U0001F519 Back to Admin", "adm_adminmain", "danger", icon=6129888444245089008)],
        ]
        try:
            return await event.edit(msg, buttons=btns)
        except Exception:
            return await bot.send_message(chat, msg, buttons=btns)

    elif action_data == "manageadmins" and is_super_admin(uid):
        return await manage_admins_menu(event)

    elif action_data.startswith("tglperm|") and is_super_admin(uid):
        _, t_id, p_name = action_data.split("|")
        if int(t_id) == 6356015122:
            return await event.answer("⚠️ Super Admin permissions cannot be modified!", alert=True)
        cur.execute(f"UPDATE admins SET {p_name} = CASE WHEN {p_name}=1 THEN 0 ELSE 1 END WHERE user_id=?", (t_id,))
        db.commit()
        return await edit_admin_menu(event, t_id)
        
    elif action_data.startswith("deladmin|") and is_super_admin(uid):
        t_id = action_data.split("|")[1]
        if int(t_id) == 6356015122:
            return await event.answer("⚠️ Super Admin cannot be removed!", alert=True)
        cur.execute("DELETE FROM admins WHERE user_id=?", (t_id,))
        db.commit()
        await event.answer("✅ Admin Removed", alert=True)
        return await manage_admins_menu(event)

    elif action_data == "managestock" and has_perm(uid, 'p_manage_stock'): return await send_manage_stock_page(event, 1)
    elif action_data == "checkstock" and has_perm(uid, 'p_manage_stock'):
        await event.answer("Checking stock started...", alert=False)
        bot.loop.create_task(run_stock_check(event))
        return
    elif action_data.startswith("mspg|") and has_perm(uid, 'p_manage_stock'): return await send_manage_stock_page(event, int(action_data.split("|")[1]))
    elif action_data.startswith("msc|") and has_perm(uid, 'p_manage_stock'): return await send_manage_stock_country(event, action_data.split("|")[1])
    elif action_data == "autoprice" and has_perm(uid, 'p_manage_stock'): return await send_autoprice_page(event, 1)
    elif action_data.startswith("appg|") and has_perm(uid, 'p_manage_stock'): return await send_autoprice_page(event, int(action_data.split("|")[1]))
    elif action_data.startswith("apc|") and has_perm(uid, 'p_manage_stock'): return await send_autoprice_country(event, action_data.split("|")[1])
        
    elif action_data == "backupusr" and has_perm(uid, 'p_settings'):
        cur.execute("SELECT * FROM users")
        with open("users_backup.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow([i[0] for i in cur.description]); w.writerows(cur.fetchall())
        await bot.send_file(chat, "users_backup.csv", caption=f"{P_USERS} <b>Users Backup CSV</b>")
        os.remove("users_backup.csv")
        return await event.answer("✅ Backup Generated!", alert=True)

    async with bot.conversation(chat, timeout=600) as conv:
        async def get_reply(txt):
            await conv.send_message(txt + "\n\n<i>(Type /cancel to abort)</i>")
            resp = await conv.get_response()
            if resp.text == "/cancel": raise ValueError("Cancelled")
            return resp

        try:
            if action_data == "ap_add_country" and has_perm(uid, 'p_manage_stock'):
                code = (await get_reply(f"{P_PHONE} <b>Enter Country Calling Code (without +):</b>\n<i>Example: 91</i>")).text.replace("+", "").strip()
                flag = html.escape((await get_reply(f"{P_FLAG} <b>Enter Country Flag Emoji:</b>\n<i>Example: 🇮🇳</i>")).text.strip())
                name = html.escape((await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).text.strip())
                
                cur.execute("INSERT OR REPLACE INTO custom_countries (code, name, flag) VALUES (?,?,?)", (code, name, flag))
                db.commit()
                await conv.send_message(f"{P_YES} <b>Custom Country Added Successfully!</b>\n{flag} {name} (+{code})\n\n<i>It will now automatically be recognized when adding stock!</i>")

            elif action_data == "walletaddr" and has_perm(uid, 'p_settings'):
                from database import set_trust_wallet_address
                addr = (await get_reply("\U0001F45B <b>Enter new USDT (BEP-20) wallet address:</b>\n<i>Example: 0x1234...abcd</i>")).text.strip()
                if len(addr) < 20:
                    await conv.send_message(f"{P_NO} That does not look like a valid wallet address.")
                else:
                    set_trust_wallet_address(addr)
                    await conv.send_message(f"{P_YES} <b>Trust Wallet address updated!</b>\n<code>{html.escape(addr)}</code>")

            elif action_data == "walletqr" and has_perm(uid, 'p_settings'):
                from database import set_trust_wallet_qr
                await conv.send_message("\U0001F5BC <b>Send the new QR photo, or paste an image URL.</b>\n\n<i>(Type /cancel to abort)</i>")
                resp = await conv.get_response()
                if resp.text == "/cancel":
                    raise ValueError("Cancelled")
                if resp.photo or resp.document:
                    os.makedirs("assets", exist_ok=True)
                    path = await resp.download_media("assets/trust_wallet_qr.png")
                    if not path:
                        await conv.send_message(f"{P_NO} Could not save that image, try again.")
                    else:
                        set_trust_wallet_qr(path)
                        await conv.send_message(f"{P_YES} <b>Custom QR saved.</b>\nIt will be sent with every USDT invoice.")
                elif resp.text and resp.text.strip().startswith("http"):
                    set_trust_wallet_qr(resp.text.strip())
                    await conv.send_message(f"{P_YES} <b>QR image URL saved.</b>")
                else:
                    await conv.send_message(f"{P_NO} Send a photo or a link starting with http.")

            elif action_data == "walletqr_clear" and has_perm(uid, 'p_settings'):
                from database import set_trust_wallet_qr
                set_trust_wallet_qr("")
                await conv.send_message(f"{P_YES} <b>Custom QR removed.</b> The bot will auto-generate a QR from the address.")

            elif action_data == "addsrc" and has_perm(uid, 'p_settings'):
                title = (await get_reply("\U0001F4BB <b>Source code title:</b>")).text.strip()
                desc = (await get_reply("\U0001F4DD <b>Short description:</b>")).text.strip()
                price_raw = (await get_reply(f"{P_INR} <b>Price in INR:</b>")).text.strip()
                try:
                    price = float(re.sub(r"[^0-9.]", "", price_raw) or "0")
                except ValueError:
                    price = 0.0
                await conv.send_message("\U0001F4E6 <b>Now send the ZIP file</b> (as a document).\n\n<i>(Type /cancel to abort)</i>")
                resp = await conv.get_response()
                if resp.text == "/cancel":
                    raise ValueError("Cancelled")
                if not resp.document:
                    await conv.send_message(f"{P_NO} That was not a file. Send the ZIP as a document.")
                else:
                    os.makedirs("assets/source_codes", exist_ok=True)
                    safe = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "source"
                    dest = f"assets/source_codes/{safe}-{int(time.time())}.zip"
                    path = await resp.download_media(dest)
                    if not path:
                        await conv.send_message(f"{P_NO} Could not save the file, try again.")
                    else:
                        cur.execute(
                            "INSERT INTO source_codes (title, description, price, file_content, available) VALUES (?,?,?,?,1)",
                            (title, desc, price, f"file:{path}"),
                        )
                        db.commit()
                        new_id = cur.lastrowid
                        await conv.send_message(
                            f"{P_YES} <b>Source code added!</b>\n\n"
                            f"\U0001F194 ID: <code>{new_id}</code>\n"
                            f"\U0001F3F7 {html.escape(title)}\n"
                            f"{P_INR} Price: <b>{price}</b>\n"
                            f"\U0001F4E6 File: <code>{html.escape(path)}</code>\n\n"
                            f"<i>Buyers receive this exact ZIP on purchase.</i>"
                        )

            elif action_data == "delsrc" and has_perm(uid, 'p_settings'):
                rows = cur.execute("SELECT id, title, price FROM source_codes ORDER BY id DESC LIMIT 20").fetchall()
                if not rows:
                    await conv.send_message(f"{P_NO} No source codes in the store.")
                else:
                    listing = "\n".join(f"\u2022 <code>{r[0]}</code> — {html.escape(str(r[1]))} ({P_INR}{r[2]})" for r in rows)
                    sid_raw = (await get_reply(f"\U0001F5D1 <b>Enter the ID to delete:</b>\n\n{listing}")).text.strip()
                    try:
                        sid = int(re.sub(r"[^0-9]", "", sid_raw) or "0")
                    except ValueError:
                        sid = 0
                    row = cur.execute("SELECT title, file_content FROM source_codes WHERE id=?", (sid,)).fetchone()
                    if not row:
                        await conv.send_message(f"{P_NO} No source code with that ID.")
                    else:
                        if (row[1] or "").startswith("file:"):
                            try:
                                os.remove(row[1].split(":", 1)[1])
                            except Exception:
                                pass
                        cur.execute("DELETE FROM source_codes WHERE id=?", (sid,))
                        db.commit()
                        await conv.send_message(f"{P_YES} <b>Deleted:</b> {html.escape(str(row[0]))}")

            elif action_data == "userinfo" and has_perm(uid, 'p_stats'):
                t_uid = int((await get_reply(f"{P_ACC} <b>Enter User ID:</b>")).text)
                u_row = cur.execute("SELECT balance, total_deposited, joined_date, banned, discount FROM users WHERE user_id=?", (t_uid,)).fetchone()
                if not u_row: return await conv.send_message(f"{P_NO} User not found.")
                
                o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (t_uid,)).fetchone()
                up_row = cur.execute("SELECT SUM(amount) FROM upi_orders WHERE user_id=? AND status='success'", (t_uid,)).fetchone()
                
                bal, dep, joined, is_banned, disc = u_row
                o_count = o_row[0] if o_row else 0
                o_spent = o_row[1] if o_row and o_row[1] else 0
                u_upi = up_row[0] if up_row and up_row[0] else 0
                
                msg = (f"{PE_USER} <b>USER INFO:</b> <code>{t_uid}</code>\n\n"
                       f"{P_MONEY} Balance: {P_INR}{bal}\n"
                       f"{P_CARD} Total Deposited: {P_INR}{dep}\n"
                       f"{P_UPI} UPI Deposited: {P_INR}{u_upi}\n"
                       f"{P_CART} Total Orders: {o_count}\n"
                       f"{P_USDT} Total Spent: {P_INR}{o_spent}\n"
                       f"{P_GIFT} Discount: {disc}%\n"
                       f"{P_CAL} Joined: {joined}\n"
                       f"{P_OFF} Banned: {'Yes' if is_banned else 'No'}")
                await conv.send_message(msg)

            elif action_data == "addadmin" and is_super_admin(uid):
                new_ad = int((await get_reply(f"{P_ACC} <b>Enter User ID for new Admin:</b>")).text)
                cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_ad,))
                db.commit()
                await conv.send_message(f"{P_YES} Admin added!")
                class FakeEvent: 
                    async def edit(self, text, buttons): await bot.send_message(chat, text, buttons=buttons)
                    async def answer(self, txt, alert): pass
                await edit_admin_menu(FakeEvent(), new_ad)
                
            elif action_data == "editadminreq" and is_super_admin(uid):
                t_id = int((await get_reply(f"{P_ACC} <b>Enter User ID to edit:</b>")).text)
                class FakeEvent: 
                    async def edit(self, text, buttons): await bot.send_message(chat, text, buttons=buttons)
                    async def answer(self, txt, alert): pass
                await edit_admin_menu(FakeEvent(), t_id)

            elif action_data.startswith("msedit|") and has_perm(uid, 'p_manage_stock'):
                parts = action_data.split("|")
                action, c_name = parts[1], parts[2]
                
                if action == "name":
                    new_name = html.escape((await get_reply(f"{P_DOC} <b>Enter NEW Name for {c_name}:</b>")).text)
                    cur.execute("UPDATE stock SET country_name=? WHERE country_name=?", (new_name, c_name))
                    cur.execute("UPDATE auto_prices SET country=? WHERE country=?", (new_name, c_name))
                    db.commit()
                    await conv.send_message(f"{P_YES} Country '{c_name}' successfully renamed to '{new_name}'!")
                    
                elif action == "flag":
                    new_flag = html.escape((await get_reply(f"{P_FLAG} <b>Enter NEW Flag Emoji for {c_name}:</b>")).text)
                    cur.execute("UPDATE stock SET country_icon=? WHERE country_name=?", (new_flag, c_name))
                    db.commit()
                    await conv.send_message(f"{P_YES} Flag updated to {new_flag} for '{c_name}'!")
                    
                elif action == "cprice":
                    new_p = int((await get_reply(f"{P_MONEY} <b>Enter NEW Common Price for all {c_name} accounts:</b>")).text)
                    cur.execute("UPDATE stock SET price=? WHERE country_name=?", (new_p, c_name))
                    db.commit()
                    await conv.send_message(f"{P_YES} All existing '{c_name}' accounts updated to {P_INR}{new_p}!")
                    
                elif action == "yprice":
                    year = parts[3]
                    new_p = int((await get_reply(f"{P_MONEY} <b>Enter NEW Price for {c_name} ({year}):</b>")).text)
                    cur.execute("UPDATE stock SET price=? WHERE country_name=? AND account_year=?", (new_p, c_name, year))
                    db.commit()
                    await conv.send_message(f"{P_YES} All existing '{c_name}' ({year}) accounts updated to {P_INR}{new_p}!")
                    
            elif action_data.startswith("apset|") and has_perm(uid, 'p_manage_stock'):
                parts = action_data.split("|")
                c_name, year = parts[1], parts[2]
                new_p = int((await get_reply(f"{P_ASST} <b>Enter Auto-Price for {c_name} ({year}):</b>\n<i>(Enter 0 to remove this auto-price)</i>")).text)
                if new_p == 0:
                    cur.execute("DELETE FROM auto_prices WHERE country=? AND year=?", (c_name, year))
                    await conv.send_message(f"{P_YES} Auto-Price for {c_name} ({year}) removed!")
                else:
                    cur.execute("INSERT OR REPLACE INTO auto_prices (country, year, price) VALUES (?,?,?)", (c_name, year, new_p))
                    await conv.send_message(f"{P_YES} Auto-Price for {c_name} ({year}) set to {P_INR}{new_p}! Incoming accounts will use this price automatically.")
                db.commit()

            elif action_data == "setchangefee" and has_perm(uid, 'p_settings'):
                curr_fee = get_change_number_fee()
                fee_text = (await get_reply(f"{P_MONEY} <b>Enter NEW Change Number Fee (in INR):</b>\n\n<i>Current Fee: ₹{curr_fee}</i>\n<i>(Enter 0 to make it free)</i>")).text
                try:
                    new_fee = int(fee_text.strip())
                    if new_fee < 0: raise ValueError()
                    set_change_number_fee(new_fee)
                    await conv.send_message(f"{P_YES} <b>Change Phone Number Service Fee updated to ₹{new_fee}!</b>")
                except:
                    await conv.send_message(f"{P_NO} Invalid fee amount. Please enter a valid positive number.")

            elif action_data == "addpay" and has_perm(uid, 'p_settings'):
                name = html.escape((await get_reply(f"{P_CARD} <b>Enter Payment Method Name:</b>\n<i>(e.g., Binance Pay, TRX)</i>")).text)
                qr_msg = await get_reply(f"📸 <b>Send QR Code Image:</b>\n<i>(Or type <code>skip</code> if no QR needed)</i>")
                qr_path = ""
                if qr_msg.photo:
                    qr_path = f"qr_{int(time.time())}.jpg"
                    await bot.download_media(qr_msg, qr_path)
                
                cap_msg = (await get_reply(f"{P_DOC} <b>Enter Payment Caption:</b>\n<i>(Use <code>text</code> to make wallet IDs or UPI copyable)</i>")).text
                cap_msg = html.escape(cap_msg).replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
                cur.execute("INSERT INTO custom_payments (name, caption, qr_file_id) VALUES (?,?,?)", (name, cap_msg, qr_path))
                db.commit()
                await conv.send_message(f"{P_YES} Payment Method '{name}' added successfully!")

            elif action_data == "delpay" and has_perm(uid, 'p_settings'):
                rows = cur.execute("SELECT id, name FROM custom_payments").fetchall()
                if not rows: return await conv.send_message(f"{P_NO} No custom payment methods.")
                msg = f"{P_DOC} <b>Reply with the ID of the method to delete:</b>\n\n"
                for r in rows: msg += f"ID: {r[0]} - {r[1]}\n"
                del_id = (await get_reply(msg)).text
                try:
                    del_id = int(del_id)
                    file_path = cur.execute("SELECT qr_file_id FROM custom_payments WHERE id=?", (del_id,)).fetchone()
                    if file_path and file_path[0] and os.path.exists(file_path[0]): os.remove(file_path[0])
                    cur.execute("DELETE FROM custom_payments WHERE id=?", (del_id,))
                    db.commit()
                    await conv.send_message(f"{P_YES} Deleted!")
                except: await conv.send_message(f"{P_NO} Invalid ID.")

            elif action_data == "addzip" and has_perm(uid, 'p_add_stock'):
                resp = await get_reply(f"{P_PKG} <b>Send the ZIP file containing <code>.session</code> files:</b>")
                if not resp.file or not resp.file.name.endswith('.zip'): return await conv.send_message(f"{P_NO} Invalid file.")
                
                await conv.send_message(f"{P_WAIT} <b>Extracting & Scanning Accounts...</b>")
                zip_path = await bot.download_media(resp, "temp_sessions.zip")
                extracted_dir = f"temp_extracted_{int(time.time())}"
                os.makedirs(extracted_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(extracted_dir)

                groups = {}
                for file in os.listdir(extracted_dir):
                    if not file.endswith(".session"): continue
                    sess_path = os.path.join(extracted_dir, file)
                    clean_path = sess_path[:-8]
                    try:
                        client = TelegramClient(clean_path, API_ID, API_HASH)
                        await client.connect()
                        if not await client.is_user_authorized(): await client.disconnect(); continue
                        me = await client.get_me()
                        phone = getattr(me, 'phone', None)
                        if not phone: await client.disconnect(); continue
                        
                        c_name, c_icon = get_country_info(phone)
                        pwd = await client(GetPasswordRequest())
                        has_2fa = pwd.has_password
                        year = await detect_account_year(client)
                        await client.disconnect()

                        key = (c_name, year, has_2fa)
                        if key not in groups: groups[key] = []
                        groups[key].append({"phone": phone, "path": clean_path, "c_icon": c_icon})
                    except Exception as e: logger.error(f"Scan error: {e}")

                for key in list(groups.keys()):
                    if key[0] == "Unknown":
                        sample_phone = groups[key][0]["phone"]
                        await conv.send_message(f"{P_WARN} <b>Country not recognized for +{sample_phone}!</b>")
                        new_icon = html.escape((await get_reply(f"{P_FLAG} <b>Enter Country Flag Emoji:</b>\n<i>Example: 🇮🇳</i>")).text)
                        new_name = html.escape((await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).text)
                        new_key = (new_name, key[1], key[2])
                        groups[new_key] = groups.pop(key)
                        for acc in groups[new_key]: acc["c_icon"] = new_icon

                success = 0
                for (c_name, year, has_2fa), accs in groups.items():
                    c_icon = accs[0]["c_icon"]
                    twofa_pass = "None"
                    if has_2fa: twofa_pass = html.escape((await get_reply(f"{P_2FA} <b>Enter 2FA Password for {len(accs)}x {c_name} accounts:</b>")).text)

                    auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=?", (c_name, str(year))).fetchone()
                    if not auto_row: auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common'", (c_name,)).fetchone()

                    if auto_row:
                        price = auto_row[0]
                        await conv.send_message(f"⚡ <b>Auto-Price Applied:</b> {len(accs)}x {c_name} ({year}) at {P_INR}{price}.")
                    else:
                        existing_price = cur.execute("SELECT price FROM stock WHERE country_name=? LIMIT 1", (c_name,)).fetchone()
                        if existing_price:
                            price = existing_price[0]
                            await conv.send_message(f"⚡ <b>Auto-Added:</b> {len(accs)}x {c_name} at {P_INR}{price} (Copied from DB).")
                        else:
                            price = int((await get_reply(f"📌 Found {len(accs)}x {c_name} ({year}).\n{P_MONEY} Enter Price (₹):")).text)

                    for acc in accs:
                        perm_base = f"sessions/{acc['phone']}"
                        for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
                            if os.path.exists(acc['path'] + ext): shutil.move(acc['path'] + ext, perm_base + ext)
                        cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?,?)", 
                                    (acc['phone'], perm_base + ".session", c_name, c_icon, year, 'Good', price, 1, twofa_pass))
                        success += 1
                db.commit()
                os.remove(zip_path); shutil.rmtree(extracted_dir)
                await conv.send_message(f"{P_YES} <b>Bulk Interactive Upload Complete!</b>\n{P_ON} Added: {success}")

            elif action_data == "addstock" and has_perm(uid, 'p_add_stock'):
                phone = (await get_reply(f"{P_PHONE} Enter Phone (+919999...):")).text.replace(" ", "").replace("+", "")
                sp = f"sessions/{phone}"
                client = TelegramClient(sp, API_ID, API_HASH)
                await client.connect()
                try:
                    sreq = await client.send_code_request(phone)
                except FloodWaitError as e:
                    wait_mins = e.seconds // 60
                    wait_hrs = wait_mins // 60
                    if wait_hrs > 0:
                        time_str = f"{wait_hrs}h {wait_mins % 60}m"
                    else:
                        time_str = f"{wait_mins}m"
                    await conv.send_message(f"⏳ <b>FloodWait!</b> Telegram rate-limited.\n\n<b>Wait:</b> {time_str}\n<i>Too many OTP requests. Try again later.</i>")
                    await client.disconnect()
                    return
                except Exception as e:
                    await conv.send_message(f"❌ <b>Error:</b> {e}\n<i>Failed to request code. This number might be rate-limited or banned.</i>")
                    await client.disconnect()
                    return
                
                twofa_pass = "None"
                try: 
                    await client.sign_in(phone, (await get_reply(f"{P_OTP} OTP:")).text, phone_code_hash=sreq.phone_code_hash)
                except SessionPasswordNeededError: 
                    twofa_pass = html.escape((await get_reply(f"{P_2FA} 2FA Pass required. Enter it now:")).text)
                    await client.sign_in(password=twofa_pass)
                
                c_name, c_icon = get_country_info(phone)
                
                if c_name == "Unknown":
                    await conv.send_message(f"{P_WARN} <b>Country not recognized for +{phone}!</b>")
                    c_icon = html.escape((await get_reply(f"{P_FLAG} <b>Enter Country Flag Emoji:</b>\n<i>Example: 🇮🇳</i>")).text)
                    c_name = html.escape((await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).text)
                
                auto_year = await detect_account_year(client)
                await client.disconnect()
                
                year = int((await get_reply(f"{P_CAL} Detected Year: <b>{auto_year}</b>\nReply with Year to confirm or change:")).text)
                auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=?", (c_name, str(year))).fetchone()
                if not auto_row: auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common'", (c_name,)).fetchone()

                if auto_row:
                    price = auto_row[0]
                    await conv.send_message(f"⚡ <b>Auto-Price Applied:</b> {P_INR}{price} for {c_name} ({year})")
                else:
                    existing_price = cur.execute("SELECT price FROM stock WHERE country_name=? LIMIT 1", (c_name,)).fetchone()
                    if existing_price:
                        price = existing_price[0]
                        await conv.send_message(f"⚡ <b>Auto-detected Price:</b> {P_INR}{price} for {c_name}")
                    else: price = int((await get_reply(f"{P_MONEY} Price (₹):")).text)
                
                cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, country_icon, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?,?)", 
                            (phone, sp + ".session", c_name, c_icon, year, 'Good', price, 1, twofa_pass))
                db.commit()
                await conv.send_message(f"{P_YES} Added!")

            elif action_data == "supporturl" and has_perm(uid, 'p_settings'):
                url = (await get_reply("🔗 Enter new Support URL (must start with http:// or https://):")).text
                if not url.startswith("http"): url = "https://" + url.replace("@", "t.me/")
                cur.execute("UPDATE settings SET value=? WHERE key='support_url'", (url,))
                db.commit()
                await conv.send_message(f"{P_YES} Support URL updated.")

            elif action_data == "bcast" and has_perm(uid, 'p_stats'):
                txt = (await get_reply(f"{P_DOC} <b>Message (Supports HTML & tg-emoji tags):</b>")).text
                btn_name = (await get_reply(f"🔘 <b>Button Name (or 'skip'):</b>")).text
                url = (await get_reply("🔗 <b>URL:</b>")).text if btn_name.lower() != 'skip' else None
                btns = [[Button.url(btn_name, url)]] if url else None
                users = cur.execute("SELECT user_id FROM users").fetchall()
                s, f = 0, 0
                total = len(users)
                status_msg = await conv.send_message(f"{P_TG} Broadcasting to {total} users...")
                for idx, (u_id,) in enumerate(users):
                    try: 
                        await bot.send_message(int(u_id), txt, buttons=btns, parse_mode='html')
                        s += 1
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds + 1)
                        try:
                            await bot.send_message(int(u_id), txt, buttons=btns, parse_mode='html')
                            s += 1
                        except Exception:
                            f += 1
                    except (UserIsBlockedError, InputUserDeactivatedError):
                        f += 1
                    except Exception:
                        f += 1
                    if (idx + 1) % 50 == 0:
                        try: await status_msg.edit(f"{P_TG} Broadcasting... {idx+1}/{total} (✅ {s} | ❌ {f})")
                        except: pass
                    await asyncio.sleep(0.05) 
                await conv.send_message(f"{P_YES} Done! Sent: {s} | Failed: {f} | Total: {total}")

            elif action_data == "bal" and has_perm(uid, 'p_bal'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).text)
                amt = int((await get_reply(f"{P_MONEY} <b>Amount (Negative to deduct):</b>")).text)
                update_balance(t_uid, amt)
                await conv.send_message(f"{P_YES} Added {P_INR}{amt} to {t_uid}.")
                
            elif action_data == "discount" and has_perm(uid, 'p_settings'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).text)
                pct = int((await get_reply(f"{P_GIFT} <b>Discount % (0 to remove):</b>")).text)
                cur.execute("UPDATE users SET discount=? WHERE user_id=?", (pct, t_uid))
                db.commit()
                await conv.send_message(f"{P_YES} User {t_uid} has {pct}% discount.")
                
            elif action_data == "refpct" and has_perm(uid, 'p_settings'):
                pct = int((await get_reply(f"{P_USERS} <b>New Referral %:</b>")).text)
                cur.execute("UPDATE settings SET value=? WHERE key='ref_percent'", (str(pct),))
                db.commit()
                await conv.send_message(f"{P_YES} Ref revenue set to {pct}%.")

            elif action_data == "usdtrate" and has_perm(uid, 'p_settings'):
                r = float((await get_reply(f"{P_USDT} <b>New USDT Rate (INR):</b>")).text)
                cur.execute("UPDATE settings SET value=? WHERE key='usdt_rate'", (str(r),))
                db.commit()
                await conv.send_message(f"{P_YES} Rate set to {r}.")

            elif action_data == "setlztkey" and has_perm(uid, 'p_settings'):
                resp = await get_reply(
                    "🔑 <b>Enter LZT Access Token:</b>\n\n"
                    "<i>lolz.live → Account → API → open your "
                    "client → <b>Get Access Token</b> → tick the "
                    "<b>market</b> scope → copy the long token "
                    "(it starts with <code>eyJ</code> and has two dots).</i>\n\n"
                    "⚠️ Do <b>not</b> send the Client ID or Client "
                    "Secret — those never work."
                )
                k = resp.text.strip()
                if k.lower().startswith("bearer "):
                    k = k[7:].strip()

                fmt_ok, fmt_reason = validate_token_format(k)
                if not fmt_ok:
                    return await conv.send_message(
                        f"{P_NO} <b>That is not an Access Token.</b>\n\n"
                        f"{fmt_reason}\n\n"
                        "<b>Where to get it:</b>\n"
                        "1. Open <b>lolz.live/account/api</b>\n"
                        "2. Click your client (e.g. <i>Mystic</i>)\n"
                        "3. Press <b>Get Access Token</b>\n"
                        "4. Tick <b>Market: search, view, purchase, put up for "
                        "sale</b>\n"
                        "5. Copy the token → send it here\n\n"
                        "<i>The token is shown only once — copy it right "
                        "away. If you lost it, press Get Access Token again.</i>"
                    )

                set_lzt_key(k)

                # Validate immediately so a bad/expired token is caught here
                # instead of silently showing "no live accounts" in the shop.
                verdict = ""
                try:
                    ok, check_msg = await asyncio.wait_for(
                        lzt_client.check_connection(), timeout=45
                    )
                    verdict = "\n\n" + check_msg
                except Exception as exc:
                    verdict = f"\n\n⚠️ Could not verify the key: {html.escape(str(exc))}"

                await conv.send_message(
                    f"{P_YES} <b>LZT API Key saved.</b>{verdict}"
                )

            elif action_data == "setrubrate" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"💹 <b>Enter RUB to INR Exchange Rate:</b>\n<i>Current: {get_rub_rate()} (Example: 1.15)</i>")
                try:
                    r = float(resp.text.strip())
                    set_rub_rate(r)
                    await conv.send_message(f"{P_YES} <b>RUB Rate set to ₹{r}</b>")
                except:
                    await conv.send_message(f"{P_NO} Invalid rate value.")

            elif action_data == "setlztmargin" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"💰 <b>Enter Profit Margin in INR (Added to base cost):</b>\n<i>Current: +₹{get_lzt_margin()} (Example: 25)</i>")
                try:
                    m = float(resp.text.strip())
                    set_lzt_margin(m)
                    # Drive the unified profit engine too, so the user price is
                    # exactly: panel_cost + ₹m  (e.g. ₹15 + ₹24 = ₹39).
                    try:
                        from utils.markup import set_markup
                        set_markup(mode="fixed", fixed=m, currency="INR")
                    except Exception:
                        pass
                    await conv.send_message(
                        f"{P_YES} <b>Profit Margin set to +₹{m:g}</b>\n"
                        f"<i>User price = panel cost + ₹{m:g} "
                        f"(e.g. ₹15 + ₹{m:g} = ₹{15 + m:g})</i>"
                    )
                except:
                    await conv.send_message(f"{P_NO} Invalid margin value.")

            elif action_data == "restoreusr" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"📤 <b>Send the <code>users_backup.csv</code> file:</b>")
                if not resp.file or not resp.file.name.endswith('.csv'): return await conv.send_message(f"{P_NO} Invalid file.")
                await bot.download_media(resp, "temp_restore.csv")
                with open("temp_restore.csv", "r", encoding="utf-8") as f:
                    reader = csv.reader(f); next(reader); count = 0
                    for row in reader:
                        try:
                            cur.execute("INSERT OR REPLACE INTO users (user_id, balance, referred_by, total_deposited, joined_date, banned, discount, terms_accepted) VALUES (?,?,?,?,?,?,?,?)", 
                                        (int(row[0]), int(row[1]), row[2] if row[2] else None, int(row[3]), row[4], int(row[5]), int(row[6]), int(row[7])))
                            count += 1
                        except: pass
                db.commit()
                os.remove("temp_restore.csv")
                await conv.send_message(f"{P_YES} Restored {count} users.")

            elif action_data == "add_fsub" and (is_super_admin(uid) or has_perm(uid, 'p_settings')):
                prompt_msg = (
                    "📢 <b>Add Must-Join (Force Sub) Channel:</b>\n\n"
                    "Aap channel ka <b>koi bhi format</b> bhej sakte hain:\n"
                    "• <b>Username:</b> <code>@mychannel</code> ya <code>mychannel</code>\n"
                    "• <b>Public Link:</b> <code>https://t.me/mychannel</code>\n"
                    "• <b>Private Link:</b> <code>https://t.me/+invitehash</code>\n"
                    "• <b>Channel ID:</b> <code>-1001234567890</code>\n"
                    "• <b>Forward:</b> Channel se koi bhi message yahan forward karein!\n\n"
                    "<i>(Make sure bot is an Admin in the channel)</i>\n"
                    "<i>Type /cancel to abort.</i>"
                )
                resp = await get_reply(prompt_msg)
                resp_text = (resp.text or "").strip()
                if resp_text.lower() in ('/cancel', 'cancel'):
                    await conv.send_message("❌ Action cancelled.")
                else:
                    from utils.helpers import resolve_channel_and_link
                    res = await resolve_channel_and_link(bot, text=resp_text, forward_msg=resp)
                    if not res.get('success'):
                        await conv.send_message(f"{P_NO} {res.get('error')}")
                    else:
                        ch_id = res['channel_id']
                        join_url = res['join_url']
                        title = res['title']
                        is_bot_adm = res['is_admin']
                        
                        add_fsub_channel(ch_id, join_url)
                        
                        if is_bot_adm:
                            status_badge = "🟢 <b>Bot Admin Verified!</b>"
                        else:
                            status_badge = (
                                "⚠️ <b>Bot is NOT an Admin!</b>\n"
                                "<i>(Channel me bot ko Admin banayein with 'Invite Users' permission taaki users verify ho sakein.)</i>"
                            )
                        
                        success_msg = (
                            f"{P_YES} <b>Must-Join Channel Added Successfully!</b>\n\n"
                            f"📌 <b>Title:</b> <b>{html.escape(str(title))}</b>\n"
                            f"🆔 <b>Channel:</b> <code>{ch_id}</code>\n"
                            f"🔗 <b>Join Link:</b> {join_url}\n"
                            f"🛡️ <b>Status:</b> {status_badge}"
                        )
                        await conv.send_message(success_msg)

            elif action_data == "add_logch" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"📝 <b>Enter Log / Approval Channel ID:</b>\n\n<i>Example:</i> <code>-1003875933534</code>\n<i>(Make sure the bot is an Admin with post permissions in the channel!)</i>")
                text = resp.text.strip()
                if text.startswith('-') and text[1:].isdigit():
                    add_log_channel_db(text)
                    await conv.send_message(f"{P_YES} <b>Log Channel Added:</b> <code>{text}</code>")
                elif text.isdigit():
                    add_log_channel_db(f"-100{text}")
                    await conv.send_message(f"{P_YES} <b>Log Channel Added:</b> <code>-100{text}</code>")
                else:
                    await conv.send_message(f"{P_NO} Invalid channel ID. It should look like <code>-1001234567890</code>.")

            elif action_data == "set_all_fsub" and has_perm(uid, 'p_settings'):
                ch_resp = await get_reply(f"📢 <b>Enter all Must-Join Channel IDs (Comma-separated):</b>\n<i>Example: -1003875933534, -1003965638370</i>")
                url_resp = await get_reply(f"🔗 <b>Enter all Join URLs (Comma-separated, same order):</b>\n<i>Example: https://t.me/RDXnetworkinghub, https://t.me/+z_62d3jVVtkzYTZl</i>")
                
                ch_list = [c.strip() for c in ch_resp.text.split(",") if c.strip()]
                url_list = [u.strip() for u in url_resp.text.split(",") if u.strip()]
                set_fsub_data(ch_list, url_list)
                await conv.send_message(f"{P_YES} <b>All Must-Join Channels & Links Updated!</b> ({len(ch_list)} channels set)")

            elif action_data == "change_upi" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"🆔 <b>Enter new UPI ID:</b>\n<i>Example: vinit-godara@fam</i>")
                new_upi = resp.text.strip()
                cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (new_upi,))
                db.commit()
                await conv.send_message(f"{P_YES} <b>UPI ID Updated:</b> <code>{new_upi}</code>")

            elif action_data == "change_gmail" and has_perm(uid, 'p_settings'):
                resp = await get_reply(f"📧 <b>Enter Gmail Address and 16-digit App Password:</b>\n\n<i>Format:</i> <code><email> <16-digit-app-password></code>\n<i>Example:</i> <code>myemail@gmail.com dqwo agxp srsw fdax</code>")
                text = resp.text.strip()
                parts = text.split(None, 1)
                if len(parts) >= 2:
                    g_email, g_pass = parts[0], parts[1]
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_user', ?)", (g_email,))
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gmail_pass', ?)", (g_pass,))
                    db.commit()
                    await conv.send_message(f"{P_YES} <b>Gmail IMAP Credentials Updated!</b>\n• Email: <code>{g_email}</code>\n• App Password: <code>{g_pass[:4]} **** **** {g_pass[-4:]}</code>")
                else:
                    await conv.send_message(f"{P_NO} Invalid format. Provide both Gmail and 16-digit App Password.")

            elif action_data == "ban" and has_perm(uid, 'p_bal'):
                t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).text)
                is_ban = cur.execute("SELECT banned FROM users WHERE user_id=?", (t_uid,)).fetchone()
                if not is_ban: return await conv.send_message(f"{P_NO} User not found.")
                ns = 0 if is_ban[0] == 1 else 1
                cur.execute("UPDATE users SET banned=? WHERE user_id=?", (ns, t_uid))
                db.commit()
                await conv.send_message(f"User {t_uid} is {'Banned 🚫' if ns == 1 else 'Unbanned ✅'}.")

        except ValueError: await conv.send_message(f"{P_NO} Cancelled.")
        except Exception as e: await conv.send_message(f"{P_NO} Error: {e}")

def register_admin_actions(bot):
    @bot.on(events.CallbackQuery(pattern=r"^adm_"))
    async def cb_admin_actions(e):
        if is_admin(e.sender_id):
            await admin_actions(e)

    @bot.on(events.NewMessage(pattern=r"^/setchangefee(?:\s+(\d+))?$"))
    async def cmd_set_change_fee(e):
        uid = e.sender_id
        if not is_admin(uid): return
        val = e.pattern_match.group(1)
        if val:
            new_fee = int(val)
            set_change_number_fee(new_fee)
            await e.reply(f"{P_YES} <b>Change Number Service Fee updated to {P_INR}{new_fee}!</b>")
        else:
            curr = get_change_number_fee()
            await e.reply(f"ℹ️ Current Change Number Fee: <b>{P_INR}{curr}</b>\n\nUsage: <code>/setchangefee 5</code> or <code>/setchangefee 10</code>")
