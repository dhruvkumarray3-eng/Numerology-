import re
import html
import asyncio
from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db, is_admin
from utils.states import get_user_lock
from config import P_INR, P_NO, PE_CHECK, PE_GIFT, logger
from utils.keyboards import style_btn, pe
from utils.smm_client import (
    SMM_SERVERS, get_smm_platforms, get_categories_for_platform,
    get_services_for_category, get_smm_service_details, get_service_inr_rate,
    get_service_panel_rate, get_service_breakdown,
    create_smm_order, get_smm_order_status, PLATFORM_ICONS, PLATFORM_PREMIUM_ICONS,
    is_server_enabled,
)

# User state dictionary for SMM orders
smm_order_state = {}

# ── Step 1: Select Server ──
async def show_smm_servers(event):
    btns = []
    any_enabled = False
    for s_id, s_info in SMM_SERVERS.items():
        p_icon = 5408995930416362034 if s_id == 1 else 5409320020058584473
        if is_server_enabled(s_id):
            any_enabled = True
            btns.append([style_btn(f"{s_info['name']}", f"smm_srv|{s_id}", "primary", icon=p_icon)])
        else:
            # Disabled by the owner: shown greyed-out as OFF so users know it
            # exists but is unavailable.  Tapping it explains why.
            btns.append([style_btn(f"{s_info['name']}  \u2014  \U0001F534 OFF", f"smm_srv|{s_id}", "danger", icon=p_icon)])

    btns.append([style_btn("\U0001F519 \U0001D401\U0001D44E\U0001D450\U0001D458 \U0001D461\U0001D560 \U0001D403\U0001D44E\U0001D460\U0001D455\U0001D44F\U0001D560\U0001D44E\U0001D45F\U0001D451", b"dashboard_main", "danger", icon=6129812419028982717)])

    if any_enabled:
        note = "\U0001F447 <b>\U0001D40F\U0001D459\U0001D452\U0001D44E\U0001D460\U0001D452 s\U0001D452\U0001D459\U0001D452\U0001D450\U0001D461 \U0001D44E \U0001D412\U0001D452\U0001D45F\U0001D463\U0001D452\U0001D45F \U0001D401\U0001D452\U0001D459\U0001D560\U0001D464:</b>"
    else:
        note = (f"{P_NO} <b>All SMM servers are currently OFF.</b>\n"
                f"<i>Please try again later or contact support.</i>")

    msg = (f"<blockquote>\U0001F680 <b>\U0001D412\U0001D560\U0001D450\U0001D456\U0001D44E\U0001D459 \U0001D40C\U0001D452\U0001D451\U0001D456\U0001D44E \U0001D412\U0001D452\U0001D45F\U0001D463\U0001D456\U0001D450\U0001D452\U0001D460 (\U0001D412\U0001D40C\U0001D40C)</b>\n\n"
           f"\u26A1 <b>\U0001D405\U0001D44E\U0001D460\U0001D461 & \U0001D408\U0001D45B\U0001D460\U0001D461\U0001D44E\U0001D45B\U0001D461 \U0001D403\U0001D452\U0001D459\U0001D456\U0001D463\U0001D452\U0001D45F\U0001D466</b> \u0493\u1D0F\u0280 \u1D00\u029F\u029F \u1D0D\u1D00\u1D0A\u1D0F\u0280 \u1D18\u029F\u1D00\u1D1B\u0493\u1D0F\u0280\u1D0Ds.\n\n"
           f"{note}</blockquote>")

    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

# ── Step 2: Select Platform (Telegram, WhatsApp, Instagram, etc.) ──
async def show_smm_platforms_menu(event, server=1):
    srv = SMM_SERVERS.get(server, SMM_SERVERS[1])
    platforms = await get_smm_platforms(server)

    if not platforms:
        # Never leave the user on a blank screen: the provider did not answer
        # (or returned an empty catalogue), so explain it and offer a retry.
        msg = (f"<blockquote>{P_NO} <b>\u26a0\ufe0f {srv['name']} is not responding</b>\n\n"
               f"The SMM provider did not return a service list. This is usually "
               f"temporary \u2014 tap <b>Retry</b> in a few seconds.</blockquote>")
        btns = [
            [style_btn("\U0001F504 \u0280\u1d07\u1d1b\u0280\u028f", f"smm_srv|{server}", "success", icon=5409098988156629257)],
            [style_btn("\U0001F519 \u1d04\u029c\u1d0f\u1d0fs\u1d07 \u1d00\u0274\u1d0f\u1d1b\u029c\u1d07\u0280 s\u1d07\u0280\u1d20\u1d07\u0280", b"smm_menu_main", "danger", icon=6129812419028982717)],
        ]
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
        return

    btns = []
    plat_row = []
    for p in platforms:
        p_icon = PLATFORM_PREMIUM_ICONS.get(p, 6129399728506412489)
        plat_row.append(style_btn(f"{p}", f"smm_plat|{server}|{p}|1", "primary", icon=p_icon))
        if len(plat_row) == 2:
            btns.append(plat_row)
            plat_row = []
    if plat_row:
        btns.append(plat_row)
        
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐒ᴇʀᴠᴇʀs", b"smm_menu_main", "danger", icon=6129812419028982717)])
    
    msg = (f"<blockquote>🌐 <b>{srv['name']} — 𝐒ᴇʟᴇᴄᴛ 𝐏ʟᴀᴛғᴏʀᴍ</b>\n\n"
           f"⚡ <b>𝐀ʟʟ 𝐒ᴏᴄɪᴀʟ 𝐌ᴇᴅɪᴀ 𝐏ʟᴀᴛғᴏʀᴍs 𝐀ᴠᴀɪʟᴀʙʟᴇ</b>\n\n"
           f"👇 <b>𝐏ʟᴇᴀsᴇ ᴄʜᴏᴏsᴇ ᴀ ᴘʟᴀᴛғᴏʀᴍ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:</b></blockquote>")
           
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

# ── Step 3: Select Category (under Platform) with Pagination ──
async def show_platform_categories(event, server, platform, page):
    limit = 6
    offset = (page - 1) * limit
    cats = await get_categories_for_platform(platform, server)
    total = len(cats)
    page_cats = cats[offset:offset+limit]
    
    if not cats:
        return await event.answer("⚠️ No categories found for this platform.", alert=True)
        
    btns = []
    for i, c_data in enumerate(page_cats):
        real_idx = offset + i
        c_name = c_data['name']
        c_count = c_data['count']
        short_name = c_name[:28] + '..' if len(c_name) > 30 else c_name
        btns.append([style_btn(f"📁 {short_name} ({c_count})", f"smm_cat|{server}|{platform}|{real_idx}|1", "primary")])
        
    nav = []
    if page > 1:
        nav.append(style_btn("⬅️ 𝐏ʀᴇᴠ", f"smm_plat|{server}|{platform}|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total:
        nav.append(style_btn("𝐍ᴇxᴛ ➡️", f"smm_plat|{server}|{platform}|{page+1}", "primary", icon=6129732880529628243))
    if nav:
        btns.append(nav)
        
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐏ʟᴀᴛғᴏʀᴍs", f"smm_srv|{server}", "danger", icon=6129812419028982717)])
    
    total_pages = max(1, (total + limit - 1) // limit)
    icon = PLATFORM_ICONS.get(platform, '🌐')
    msg = (f"<blockquote>{icon} <b>𝐒ᴇʟᴇᴄᴛ 𝐂ᴀᴛᴇɢᴏʀʏ ғᴏʀ {platform}:</b>\n\n"
           f"📄 <b>𝐏ᴀɢᴇ:</b> <code>{page}/{total_pages}</code> (𝐓ᴏᴛᴀʟ: {total} ᴄᴀᴛᴇɢᴏʀɪᴇs)</blockquote>")
           
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

# ── Step 4: Select Service (under Category) with Pagination ──
async def show_category_services(event, server, platform, cat_idx, page):
    cats = await get_categories_for_platform(platform, server)
    if cat_idx >= len(cats):
        return await event.answer("⚠️ Category not found.", alert=True)
        
    cat_name = cats[cat_idx]['name']
    services = await get_services_for_category(cat_name, server)
    total = len(services)
    
    limit = 6
    offset = (page - 1) * limit
    page_services = services[offset:offset+limit]
    
    btns = []
    for s in page_services:
        s_id = s.get('service')
        s_name = s.get('name', 'Service')
        rate_inr = get_service_inr_rate(s, server)
        short_name = s_name[:26] + '..' if len(s_name) > 28 else s_name
        btns.append([style_btn(f"{short_name} — {P_INR}{rate_inr}/1k", f"smm_srv_info|{server}|{platform}|{cat_idx}|{s_id}", "primary", icon="cart")])
        
    nav = []
    if page > 1:
        nav.append(style_btn("⬅️ 𝐏ʀᴇᴠ", f"smm_cat|{server}|{platform}|{cat_idx}|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total:
        nav.append(style_btn("𝐍ᴇxᴛ ➡️", f"smm_cat|{server}|{platform}|{cat_idx}|{page+1}", "primary", icon=6129732880529628243))
    if nav:
        btns.append(nav)
        
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐂ᴀᴛᴇɢᴏʀɪᴇs", f"smm_plat|{server}|{platform}|1", "danger", icon=6129812419028982717)])
    
    total_pages = max(1, (total + limit - 1) // limit)
    msg = (f"<blockquote>📁 <b>𝐂ᴀᴛᴇɢᴏʀʏ:</b> <code>{html.escape(cat_name)}</code>\n\n"
           f"📄 <b>𝐏ᴀɢᴇ:</b> <code>{page}/{total_pages}</code> (𝐓ᴏᴛᴀʟ: {total} sᴇʀᴠɪᴄᴇs)\n"
           f"👇 <b>𝐒ᴇʟᴇᴄᴛ ᴀ sᴇʀᴠɪᴄᴇ ᴛᴏ ᴠɪᴇᴡ ᴅᴇᴛᴀɪʟs & ᴏʀᴅᴇʀ:</b></blockquote>")
           
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

# ── Step 5: Service Overview Card ──
async def show_service_card(event, server, platform, cat_idx, service_id):
    s = await get_smm_service_details(service_id, server)
    if not s:
        return await event.answer("\u274c Service details unavailable.", alert=True)

    s_name = s.get('name', 'Service')
    panel_rate, profit_rate, rate_inr = get_service_breakdown(s, server)
    min_q = s.get('min', 10)
    max_q = s.get('max', 100000)
    desc = s.get('desc', '') or s.get('description', '')
    money_icon = pe('money', '\U0001F4B0')
    desc_text = f"\n\U0001F4DD <b>\U0001D53B\U0001D556\U0001D564\U0001D554\U0001D563\U0001D55A\U0001D561\U0001D565\U0001D55A\U0001D560\U0001D55F:</b>\n<i>{html.escape(desc[:200])}</i>\n" if desc else ""

    msg = (f"<blockquote>\U0001F680 <b>\U0001D412\U0001D40C\U0001D40C \U0001D412\U0001D452\U0001D45F\U0001D463\U0001D456\U0001D450\U0001D452 \U0001D403\U0001D452\U0001D461\U0001D44E\U0001D456\U0001D459\U0001D460</b>\n\n"
           f"\U0001F3F7\uFE0F <b>\U0001D412\U0001D452\U0001D45F\U0001D463\U0001D456\U0001D450\U0001D452:</b> <code>{html.escape(s_name)}</code>\n"
           f"\U0001F194 <b>\U0001D412\U0001D452\U0001D45F\U0001D463\U0001D456\U0001D450\U0001D452 \U0001D408\U0001D403:</b> <code>{service_id}</code>\n"
           f"\U0001F4E6 <b>\U0001D40F\U0001D44E\U0001D45B\U0001D452\U0001D459 \U0001D411\U0001D44E\U0001D461\U0001D452:</b> <code>{P_INR}{panel_rate}/1k</code>\n"
           f"{money_icon} <b>\U0001D418\U0001D560\U0001D566\U0001D563 \U0001D40F\U0001D563\U0001D560\U0001D557\U0001D55A\U0001D565:</b> <code>+{P_INR}{profit_rate}/1k</code>\n"
           f"\U0001F4B5 <b>\U0001D418\U0001D560\U0001D566\U0001D563 \U0001D40F\U0001D563\U0001D55A\U0001D554\U0001D452:</b> <code>{P_INR}{rate_inr}/1k</code>\n"
           f"\U0001F4CA <b>\U0001D40C\U0001D456\U0001D45B / \U0001D40C\U0001D44E\U0001D465:</b> <code>{min_q} - {max_q}</code>{desc_text}\n"
           f"<i>Final price = panel rate + owner profit, so your margin is always included.</i></blockquote>")

    btns = [
        [style_btn("\U0001F6D2 \U0001D40E\U0001D45F\U0001D451\U0001D452\U0001D45F \U0001D40D\U0001D560\U0001D464", f"smm_ord_start|{server}|{platform}|{cat_idx}|{service_id}", "success", icon="buy")],
        [style_btn("\U0001F519 \U0001D401\U0001D44E\U0001D450\U0001D458 \U0001D461\U0001D560 \U0001D412\U0001D452\U0001D45F\U0001D463\U0001D456\U0001D450\U0001D452\U0001D460", f"smm_cat|{server}|{platform}|{cat_idx}|1", "danger", icon="back")]
    ]

    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

def register_smm(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/smm(?:@\w+)?$"))
    async def cmd_smm(e):
        # /smm was documented in the help menu but had no handler, so typing it
        # did nothing.  show_smm_servers() works for both messages and
        # callbacks, so it is safe to reuse here.
        await show_smm_servers(e)

    @bot.on(events.CallbackQuery(pattern=b"^smm_menu_main$"))
    async def cb_smm_main(e):
        await show_smm_servers(e)
        
    @bot.on(events.CallbackQuery(pattern=r"^smm_srv\|(\d+)$"))
    async def cb_smm_srv(e):
        srv_id = int(e.pattern_match.group(1).decode())
        if not is_server_enabled(srv_id):
            return await e.answer(
                "\U0001F534 This SMM server is currently OFF. Please choose another server.",
                alert=True,
            )
        await show_smm_platforms_menu(e, server=srv_id)
        
    @bot.on(events.CallbackQuery(pattern=r"^smm_plat\|(\d+)\|([^|]+)\|(\d+)$"))
    async def cb_smm_plat(e):
        p = e.pattern_match
        server = int(p.group(1).decode())
        platform = p.group(2).decode()
        page = int(p.group(3).decode())
        await show_platform_categories(e, server, platform, page)
        
    @bot.on(events.CallbackQuery(pattern=r"^smm_cat\|(\d+)\|([^|]+)\|(\d+)\|(\d+)$"))
    async def cb_smm_cat(e):
        p = e.pattern_match
        server = int(p.group(1).decode())
        platform = p.group(2).decode()
        cat_idx = int(p.group(3).decode())
        page = int(p.group(4).decode())
        await show_category_services(e, server, platform, cat_idx, page)
        
    @bot.on(events.CallbackQuery(pattern=r"^smm_srv_info\|(\d+)\|([^|]+)\|(\d+)\|(\d+)$"))
    async def cb_smm_srv_info(e):
        p = e.pattern_match
        server = int(p.group(1).decode())
        platform = p.group(2).decode()
        cat_idx = int(p.group(3).decode())
        service_id = int(p.group(4).decode())
        await show_service_card(e, server, platform, cat_idx, service_id)
        
    @bot.on(events.CallbackQuery(pattern=r"^smm_ord_start\|(\d+)\|([^|]+)\|(\d+)\|(\d+)$"))
    async def cb_smm_ord_start(e):
        p = e.pattern_match
        uid = e.sender_id
        server = int(p.group(1).decode())
        platform = p.group(2).decode()
        cat_idx = int(p.group(3).decode())
        service_id = int(p.group(4).decode())
        
        s = await get_smm_service_details(service_id, server)
        if not s:
            return await e.answer("❌ Service details unavailable.", alert=True)
            
        smm_order_state[uid] = {
            'stage': 'await_link',
            'server': server,
            'platform': platform,
            'cat_idx': cat_idx,
            'service_id': service_id,
            'service': s,
            'msg_id': e.message_id
        }
        
        msg = (f"<blockquote>🔗 <b>𝐏ʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ᴛᴀʀɢᴇᴛ 𝐋ɪɴᴋ:</b>\n"
               f"<i>(ᴇ.ɢ., 𝐏ʀᴏғɪʟᴇ 𝐔𝐑𝐋, 𝐏ᴏsᴛ 𝐔𝐑𝐋, 𝐂ʜᴀɴɴᴇʟ 𝐋ɪɴᴋ)</i></blockquote>")
        btns = [[style_btn("❌ 𝐂ᴀɴᴄᴇʟ", "smm_cancel", "danger", icon=6129888444245089008)]]
        try: await e.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass

    @bot.on(events.CallbackQuery(pattern=b"^smm_cancel$"))
    async def cb_smm_cancel(e):
        uid = e.sender_id
        state = smm_order_state.pop(uid, None)
        if state:
            server = state.get('server', 1)
            platform = state.get('platform', 'Telegram')
            cat_idx = state.get('cat_idx', 0)
            service_id = state.get('service_id')
            await show_service_card(e, server, platform, cat_idx, service_id)
        else:
            await show_smm_servers(e)

    @bot.on(events.NewMessage(func=lambda e: e.sender_id in smm_order_state and not (e.text or "").startswith('/')))
    async def msg_smm_order_inputs(e):
        uid = e.sender_id
        state = smm_order_state.get(uid)
        if not state: return
        
        stage = state.get('stage')
        text = (e.text or "").strip()
        
        if stage == 'await_link':
            if len(text) < 3 or (" " in text and not text.startswith("http") and not text.startswith("@") and not text.startswith("t.me")):
                return await e.reply(f"{P_NO} <b>Invalid link!</b> Please send a valid link or @username.")
                
            state['link'] = text
            state['stage'] = 'await_qty'
            s = state['service']
            min_q = s.get('min', 10)
            max_q = s.get('max', 100000)
            
            msg = (f"<blockquote>🔢 <b>𝐄ɴᴛᴇʀ 𝐐ᴜᴀɴᴛɪᴛʏ:</b>\n"
                   f"<i>(𝐌ɪɴ: <code>{min_q}</code> | 𝐌ᴀx: <code>{max_q}</code>)</i></blockquote>")
            btns = [[style_btn("❌ 𝐂ᴀɴᴄᴇʟ", "smm_cancel", "danger", icon=6129888444245089008)]]
            await e.reply(msg, buttons=btns)
            
        elif stage == 'await_qty':
            if not text.isdigit():
                return await e.reply(f"{P_NO} <b>Invalid quantity!</b> Please send numeric digits only.")
                
            qty = int(text)
            s = state['service']
            min_q = int(s.get('min', 10))
            max_q = int(s.get('max', 100000))
            
            if qty < min_q or qty > max_q:
                return await e.reply(f"{P_NO} <b>Quantity out of range!</b>\nMust be between <code>{min_q}</code> and <code>{max_q}</code>.")
                
            server = state['server']
            panel_rate, profit_rate, rate_inr = get_service_breakdown(s, server)
            total_price = max(1.0, round((rate_inr * qty) / 1000, 2))
            
            state['qty'] = qty
            state['total_price'] = total_price
            state['stage'] = 'confirm'
            
            msg = (f"<blockquote>🧾 <b>𝐂ᴏɴғɪʀᴍ 𝐒𝐌𝐌 𝐎ʀᴅᴇʀ</b>\n\n"
                   f"🚀 <b>𝐒ᴇʀᴠɪᴄᴇ:</b> <code>{html.escape(s.get('name', ''))}</code>\n"
                   f"🔗 <b>𝐋ɪɴᴋ:</b> <code>{html.escape(state['link'])}</code>\n"
                   f"🔢 <b>𝐐ᴜᴀɴᴛɪᴛʏ:</b> <code>{qty}</code>\n"
                   f"\U0001F4E6 <b>Panel Rate:</b> <code>{P_INR}{panel_rate}/1k</code>\n"
                   f"\U0001F4B0 <b>Your Profit:</b> <code>+{P_INR}{profit_rate}/1k</code>\n"
                   f"\U0001F4B5 <b>Your Rate:</b> <code>{P_INR}{rate_inr}/1k</code>\n"
                   f"💰 <b>𝐓ᴏᴛᴀʟ 𝐏ʀɪᴄᴇ:</b> <code>{P_INR}{total_price}</code>\n\n"
                   f"<b>𝐀ʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʟᴀᴄᴇ ᴛʜɪs ᴏʀᴅᴇʀ?</b></blockquote>")
                   
            btns = [
                [style_btn("✅ 𝐂ᴏɴғɪʀᴍ & 𝐏ᴀʏ", "smm_ord_confirm", "success", icon=5409320020058584473)],
                [style_btn("❌ 𝐂ᴀɴᴄᴇʟ", "smm_cancel", "danger", icon=6129888444245089008)]
            ]
            await e.reply(msg, buttons=btns)

    @bot.on(events.CallbackQuery(pattern=b"^smm_ord_confirm$"))
    async def cb_smm_ord_confirm(e):
        uid = e.sender_id
        state = smm_order_state.pop(uid, None)
        if not state or 'qty' not in state:
            return await e.answer("⚠️ Session expired. Please start over.", alert=True)
            
        total_price = state['total_price']
        service_id = state['service_id']
        link = state['link']
        qty = state['qty']
        server = state['server']
        s = state['service']

        # The owner may have switched this server OFF mid-session.
        if not is_server_enabled(server):
            return await e.answer(
                "\U0001F534 This SMM server was switched OFF. Please start again.",
                alert=True,
            )
        
        async with get_user_lock(uid):
            bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
            if not bal_row or bal_row[0] < total_price:
                return await e.answer(f"❌ Insufficient Balance! Required: ₹{total_price}, Balance: ₹{bal_row[0] if bal_row else 0}", alert=True)
                
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (total_price, uid, total_price))
            db.commit()
            
        loading = await e.reply("⏳ <i>Submitting order to SMM Server...</i>")
        api_res = await create_smm_order(service_id, link, qty, server)
        
        if api_res and 'order' in api_res:
            smm_order_id = str(api_res['order'])
            cur.execute("INSERT INTO smm_orders (user_id, server, service_id, service_name, target_link, quantity, price, smm_order_id, status) VALUES (?,?,?,?,?,?,?,?,?)",
                        (uid, server, service_id, s.get('name', ''), link, qty, total_price, smm_order_id, 'Processing'))
            db.commit()
            
            from database import get_log_channels_db
            for ch in get_log_channels_db():
                try:
                    admin_log = (f"<blockquote><b>🚀 𝐍ᴇᴡ 𝐒𝐌𝐌 𝐎ʀᴅᴇʀ</b>\n\n"
                                 f"👤 <b>𝐔sᴇʀ:</b> <code>{uid}</code>\n"
                                 f"🆔 <b>𝐒𝐌𝐌 𝐎ʀᴅᴇʀ 𝐈𝐃:</b> <code>#{smm_order_id}</code>\n"
                                 f"🏷️ <b>𝐒ᴇʀᴠɪᴄᴇ:</b> {html.escape(s.get('name', ''))}\n"
                                 f"🔗 <b>𝐋ɪɴᴋ:</b> <code>{html.escape(link)}</code>\n"
                                 f"🔢 <b>𝐐ᴜᴀɴᴛɪᴛʏ:</b> <code>{qty}</code>\n"
                                 f"💰 <b>𝐏ʀɪᴄᴇ:</b> {P_INR}{total_price}</blockquote>")
                    await bot.send_message(ch, admin_log)
                except: pass
                
            msg = (f"<blockquote>{PE_CHECK} <b>🎉 𝐒𝐌𝐌 𝐎ʀᴅᴇʀ 𝐏ʟᴀᴄᴇᴅ 𝐒ᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                   f"🆔 <b>𝐎ʀᴅᴇʀ 𝐈𝐃:</b> <code>#{smm_order_id}</code>\n"
                   f"🚀 <b>𝐒ᴇʀᴠɪᴄᴇ:</b> <code>{html.escape(s.get('name', ''))}</code>\n"
                   f"🔗 <b>𝐋ɪɴᴋ:</b> <code>{html.escape(link)}</code>\n"
                   f"🔢 <b>𝐐ᴜᴀɴᴛɪᴛʏ:</b> <code>{qty}</code>\n"
                   f"💰 <b>𝐀ᴍᴏᴜɴᴛ 𝐃ᴇᴅᴜᴄᴛᴇᴅ:</b> <code>{P_INR}{total_price}</code>\n"
                   f"📊 <b>𝐒ᴛᴀᴛᴜs:</b> <code>Processing</code></blockquote>")
                   
            btns = [
                [style_btn("🚀 𝐁ᴜʏ 𝐌ᴏʀᴇ 𝐒ᴇʀᴠɪᴄᴇs", b"smm_menu_main", "primary", icon=5408995930416362034)],
                [style_btn("🔙 𝐌ᴀɪɴ 𝐌ᴇɴᴜ", b"dashboard_main", "danger", icon=6129812419028982717)]
            ]
            await loading.edit(msg, buttons=btns)
            try:
                from utils import stickers as _sticker_engine
                await _sticker_engine.send_purchase_for_event(e)
            except Exception as _sk_ex:
                logger.debug(f"purchase emoji skipped: {_sk_ex}")
        else:
            # SMM Order failed -> refund user
            err_msg = api_res.get('error', 'API submission failed')
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (total_price, uid))
            db.commit()
            await loading.edit(f"<blockquote>{P_NO} <b>❌ 𝐎ʀᴅᴇʀ 𝐅ᴀɪʟᴇᴅ!</b>\n\n{html.escape(str(err_msg))}\n\n𝐘ᴏᴜʀ ᴍᴏɴᴇʏ (<b>{P_INR}{total_price}</b>) ʜᴀs ʙᴇᴇɴ <b>ʀᴇғᴜɴᴅᴇᴅ</b>.</blockquote>", buttons=[[style_btn("🔙 𝐁ᴀᴄᴋ ᴛᴏ 𝐒𝐌𝐌", b"smm_menu_main", "primary")]])
