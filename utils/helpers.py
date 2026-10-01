Import random
import asyncio
import re
from telethon import Button
from telethon.errors import UserNotParticipantError, ChatAdminRequiredError
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl import types, functions
from database import get_fsub_channels, get_fsub_urls, get_fsub_status
from config import logger

INVITE_REGEX = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', re.IGNORECASE)
PUBLIC_REGEX = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{3,})', re.IGNORECASE)

def format_join_url(url: str) -> str:
    """Normalizes any Telegram link or username into a valid https://t.me/... URL."""
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("t.me/") or url.startswith("telegram.me/"):
        return f"https://{url}"
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    if not (url.startswith("-") or url.isdigit()):
        return f"https://t.me/{url}"
    return url

async def resolve_channel_and_link(bot, text: str = "", forward_msg=None):
    """
    Intelligently parses any format:
    - Forwarded message from a channel
    - @username or username
    - https://t.me/username or t.me/username
    - https://t.me/+hash or t.me/+hash or t.me/joinchat/hash (private invite)
    - -1001234567890 (channel ID)
    - -1001234567890 https://t.me/... (space or newline separated)
    - https://t.me/... -1001234567890
    
    Returns:
    {
        'success': bool,
        'channel_id': str,
        'join_url': str,
        'title': str,
        'is_admin': bool,
        'error': str or None
    }
    """
    channel_id = None
    join_url = None
    title = "Channel"
    is_bot_admin = False

    # 1. Check if input is a forwarded message from a channel
    if forward_msg and getattr(forward_msg, 'forward', None):
        fwd = forward_msg.forward
        chat = getattr(fwd, 'chat', None)
        if chat:
            chat_id = getattr(chat, 'id', None) or getattr(fwd, 'chat_id', None)
            if chat_id:
                channel_id = str(chat_id)
                if not channel_id.startswith("-100"):
                    channel_id = f"-100{channel_id}"
            title = getattr(chat, 'title', getattr(chat, 'first_name', 'Channel'))
            username = getattr(chat, 'username', None)
            if username:
                join_url = f"https://t.me/{username}"

    # 2. Parse text if provided
    text = (text or "").strip()
    if text:
        parts = [p.strip() for p in re.split(r'[\s,\n]+', text) if p.strip()]
        if len(parts) >= 2:
            p1, p2 = parts[0], parts[1]
            if INVITE_REGEX.search(p1) or PUBLIC_REGEX.search(p1) or p1.startswith("http"):
                join_url = format_join_url(p1)
                channel_id = p2
            else:
                channel_id = p1
                join_url = format_join_url(p2)
        elif len(parts) == 1:
            p = parts[0]
            inv_m = INVITE_REGEX.search(p)
            if inv_m:
                join_url = format_join_url(p)
                inv_hash = inv_m.group(1)
                try:
                    from telethon.tl.functions.messages import CheckChatInviteRequest
                    inv_res = await bot(CheckChatInviteRequest(hash=inv_hash))
                    chat_obj = getattr(inv_res, 'chat', None)
                    if chat_obj:
                        c_id = getattr(chat_obj, 'id', None)
                        if c_id:
                            channel_id = str(c_id)
                            if not channel_id.startswith("-100"):
                                channel_id = f"-100{channel_id}"
                        title = getattr(chat_obj, 'title', title)
                    else:
                        title = getattr(inv_res, 'title', title)
                        channel_id = join_url
                except Exception:
                    channel_id = join_url
            else:
                pub_m = PUBLIC_REGEX.search(p)
                if pub_m:
                    username = pub_m.group(1)
                    join_url = f"https://t.me/{username}"
                    channel_id = f"@{username}"
                elif p.startswith("@"):
                    username = p[1:]
                    join_url = f"https://t.me/{username}"
                    channel_id = f"@{username}"
                elif (p.startswith("-") and p[1:].isdigit()) or p.isdigit():
                    channel_id = p if p.startswith("-100") else (f"-100{p}" if not p.startswith("-") else p)
                else:
                    # Bare username word
                    username = p
                    join_url = f"https://t.me/{username}"
                    channel_id = f"@{username}"

    if not channel_id and not join_url:
        return {
            'success': False,
            'channel_id': '',
            'join_url': '',
            'title': '',
            'is_admin': False,
            'error': "Koi valid Channel ID, Username ya Link nahi mila. Kripya valid username, link ya forwarded message bhejein."
        }

    # 3. Resolve Entity in Telethon to get exact numeric ID and title
    target_for_entity = channel_id or join_url
    entity = None
    try:
        target = int(target_for_entity) if ((str(target_for_entity).startswith('-') and str(target_for_entity)[1:].isdigit()) or str(target_for_entity).isdigit()) else target_for_entity
        entity = await bot.get_entity(target)
    except Exception:
        if join_url and join_url != target_for_entity:
            try:
                entity = await bot.get_entity(join_url)
            except Exception:
                pass

    if entity:
        title = getattr(entity, 'title', getattr(entity, 'first_name', title))
        e_id = str(entity.id)
        channel_id = f"-100{e_id}" if not e_id.startswith("-100") else e_id
        
        # If join_url not yet set, generate it
        if not join_url:
            username = getattr(entity, 'username', None)
            if username:
                join_url = f"https://t.me/{username}"
            else:
                try:
                    from telethon.tl.functions.messages import ExportChatInviteRequest
                    exp = await bot(ExportChatInviteRequest(peer=entity))
                    join_url = exp.link
                except Exception:
                    pass

    # Ensure join_url is properly formatted
    if join_url:
        join_url = format_join_url(join_url)
    elif channel_id:
        if str(channel_id).startswith("@"):
            join_url = f"https://t.me/{str(channel_id)[1:]}"
        else:
            join_url = f"https://t.me/c/{str(channel_id).replace('-100', '')}/1"

    # 4. Verify whether bot is an Admin in the channel
    try:
        bot_me = await bot.get_me()
        check_target = entity if entity else (int(channel_id) if ((str(channel_id).startswith('-') and str(channel_id)[1:].isdigit()) or str(channel_id).isdigit()) else channel_id)
        part = await bot(GetParticipantRequest(channel=check_target, participant=bot_me.id))
        part_obj = getattr(part, 'participant', None)
        if isinstance(part_obj, (types.ChannelParticipantAdmin, types.ChannelParticipantCreator)):
            is_bot_admin = True
    except Exception:
        is_bot_admin = False

    return {
        'success': True,
        'channel_id': channel_id,
        'join_url': join_url,
        'title': title,
        'is_admin': is_bot_admin,
        'error': None
    }

async def check_channel_joined(bot, uid, is_admin_func):
    """Returns True if all required channels joined, False otherwise."""
    if is_admin_func(uid): return True
    if get_fsub_status() == 'off': return True
    
    check_channels = get_fsub_channels()
    if not check_channels: return True
    
    for ch in check_channels:
        try:
            ch_str = str(ch).strip()
            if not ch_str: continue
            
            # Skip raw invite links that cannot be checked as entities directly
            if "t.me/+" in ch_str or "joinchat" in ch_str:
                continue

            target = int(ch_str) if ((ch_str.startswith('-') and ch_str[1:].isdigit()) or ch_str.isdigit()) else ch_str
            entity = None
            try:
                entity = await bot.get_entity(target)
            except Exception:
                pass
            
            peer = entity if entity is not None else target
            await bot(GetParticipantRequest(channel=peer, participant=uid))
        except UserNotParticipantError:
            return False
        except ChatAdminRequiredError:
            logger.warning(f"⚠️ Bot is NOT an admin in channel {ch}! Bypassing check to prevent user lockout.")
            continue
        except Exception as e:
            logger.warning(f"Channel Check warning for {ch}: {e}")
            continue
    return True

async def get_unjoined_channels(bot, uid):
    """Returns list of (url, index) for channels the user has NOT joined."""
    unjoined = []
    if get_fsub_status() == 'off': return []
    
    check_channels = get_fsub_channels()
    join_urls = get_fsub_urls()
    
    for i, ch in enumerate(check_channels):
        raw_url = join_urls[i] if i < len(join_urls) else ""
        url = format_join_url(raw_url)
        if not url: continue
        
        try:
            ch_str = str(ch).strip()
            if not ch_str: continue
            
            if "t.me/+" in ch_str or "joinchat" in ch_str:
                continue

            target = int(ch_str) if ((ch_str.startswith('-') and ch_str[1:].isdigit()) or ch_str.isdigit()) else ch_str
            entity = None
            try:
                entity = await bot.get_entity(target)
            except Exception:
                pass
            
            peer = entity if entity is not None else target
            await bot(GetParticipantRequest(channel=peer, participant=uid))
        except UserNotParticipantError:
            unjoined.append((url, i + 1))
        except ChatAdminRequiredError:
            logger.warning(f"⚠️ Bot is not admin in channel {ch}! Skipping unjoined list.")
            continue
        except Exception as e:
            logger.warning(f"Channel Check warning for {ch}: {e}")
            continue
    return unjoined

SMALL_CAPS_MAP = {
    'A': '𝐀', 'B': '𝐁', 'C': '𝐂', 'D': '𝐃', 'E': '𝐄', 'F': '𝐅', 'G': '𝐆', 'H': '𝐇', 'I': '𝐈', 'J': '𝐉', 'K': '𝐊', 'L': '𝐋', 'M': '𝐌', 'N': '𝐍', 'O': '𝐎', 'P': '𝐏', 'Q': '𝐐', 'R': '𝐑', 'S': '𝐒', 'T': '𝐓', 'U': '𝐔', 'V': '𝐕', 'W': '𝐖', 'X': '𝐗', 'Y': '𝐘', 'Z': '𝐙',
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
}

def to_small_caps(text):
    if not text: return ""
    return "".join(SMALL_CAPS_MAP.get(c, c) for c in str(text))

async def send_preview_on_top(bot, peer, message, url, buttons=None, edit_msg_id=None):
    """Sends or edits a message with WebPage link preview inverted ON TOP."""
    try:
        text, entities = await bot._parse_message_text(message, 'html')
        markup = bot.build_reply_markup(buttons) if buttons else None
        peer_obj = await bot.get_input_entity(peer)
        media_obj = types.InputMediaWebPage(url=url, force_large_media=True)
        
        if edit_msg_id:
            try:
                return await bot(functions.messages.EditMessageRequest(
                    peer=peer_obj,
                    id=edit_msg_id,
                    message=text,
                    entities=entities,
                    media=media_obj,
                    invert_media=True,
                    reply_markup=markup
                ))
            except Exception as e:
                logger.error(f"Edit invert_media error: {e}")
                
        return await bot(functions.messages.SendMediaRequest(
            peer=peer_obj,
            media=media_obj,
            message=text,
            entities=entities,
            invert_media=True,
            reply_markup=markup,
            random_id=random.randint(0, 2**63 - 1)
        ))
    except Exception as ex:
        logger.error(f"send_preview_on_top fallback: {ex}")
        if edit_msg_id:
            try: return await bot.edit_message(peer, edit_msg_id, message, buttons=buttons, parse_mode='html', link_preview=True)
            except: pass
        return await bot.send_message(peer, message, buttons=buttons, parse_mode='html', link_preview=True)

