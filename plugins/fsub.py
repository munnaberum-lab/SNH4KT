"""Force subscribe: normal, request-to-join, try again, per-group mute until joined."""
import logging

from pyrogram import Client, filters
from pyrogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from bothelpers import say
from utils import sc
from database import join_reqs

log = logging.getLogger("fsub")
_links = {}


async def is_member(client, chat, uid):
    try:
        m = await client.get_chat_member(chat, uid)
    except Exception as e:  # noqa
        if type(e).__name__ == "UserNotParticipant":
            return False
        log.warning("membership check failed for %s in %s: %s", uid, chat, e)
        return True  # do not lock everybody out when the check itself is broken
    return str(m.status.name) not in ("BANNED", "LEFT")


async def invite_link(client, chat, request_mode=None):
    request_mode = info.REQUEST_TO_JOIN_MODE if request_mode is None else request_mode
    key = (chat, request_mode)
    if key not in _links:
        try:
            if request_mode:
                _links[key] = (await client.create_chat_invite_link(chat, creates_join_request=True)).invite_link
            else:
                _links[key] = await client.export_chat_invite_link(chat)
        except Exception as e:  # noqa
            log.warning("invite link failed for %s: %s", chat, e)
            try:
                c = await client.get_chat(chat)
                return f"https://t.me/{c.username}" if c.username else None
            except Exception:  # noqa
                return None
    return _links[key]


async def check(client, uid, payload=None):
    """None when the user may continue, else (text, markup) asking them to join."""
    chan = info.AUTH_CHANNEL
    if not chan or uid in info.ADMINS:
        return None
    if await is_member(client, chan, uid):
        return None
    if info.REQUEST_TO_JOIN_MODE and await join_reqs.has(uid, chan):
        return None
    link = await invite_link(client, chan)
    rows = []
    if link:
        rows.append([InlineKeyboardButton("📢 " + sc("join channel") if not info.REQUEST_TO_JOIN_MODE else "📨 " + sc("send join request"), url=link)])
    if info.TRY_AGAIN_BTN and payload:
        rows.append([InlineKeyboardButton("🔄 " + sc("try again"), callback_data=f"chk#{payload}")])
    text = texts.JOIN_FIRST + (("\n\n" + texts.JOIN_REQ_SENT) if info.REQUEST_TO_JOIN_MODE else "")
    return text, InlineKeyboardMarkup(rows) if rows else None


@Client.on_chat_join_request(filters.chat(info.AUTH_CHANNEL))
async def on_join_request(client, req):
    await join_reqs.add(req.from_user.id, req.chat.id)


@Client.on_callback_query(filters.regex(r"^chk#"))
async def try_again(client, query):
    from plugins.delivery import handle_payload
    payload = query.data.split("#", 1)[1]
    if await check(client, query.from_user.id, payload):
        return await query.answer("You have not joined yet.", show_alert=True)
    await query.answer()
    try:
        await query.message.delete()
    except Exception:  # noqa
        pass
    await handle_payload(client, query.from_user, query.message.chat.id, payload)


# ---- per-group force subscribe (mute until joined) ------------------------
async def group_block(client, message, channel):
    """True when the user was muted because they have not joined the group's channel."""
    uid = message.from_user.id
    if not channel or await is_member(client, channel, uid):
        return False
    try:
        await client.restrict_chat_member(message.chat.id, uid, ChatPermissions())
    except Exception as e:  # noqa
        log.warning("cannot mute %s: %s", uid, e)
        return False
    link = await invite_link(client, channel, request_mode=False)
    rows = [[InlineKeyboardButton("📢 Join channel", url=link)]] if link else []
    rows.append([InlineKeyboardButton("🔓 Unmute me", callback_data=f"um#{message.chat.id}#{uid}")])
    await say(client, message.chat.id, f"{message.from_user.mention}, join the channel first. You are muted until you join.", InlineKeyboardMarkup(rows))
    return True


@Client.on_callback_query(filters.regex(r"^um#"))
async def unmute(client, query):
    _, chat, uid = query.data.split("#")
    chat, uid = int(chat), int(uid)
    if query.from_user.id != uid:
        return await query.answer("This button is not for you.", show_alert=True)
    from database import groups
    g = await groups.get_settings(chat)
    if not await is_member(client, g.get("fsub"), uid):
        return await query.answer("Join the channel first.", show_alert=True)
    try:
        c = await client.get_chat(chat)
        await client.restrict_chat_member(chat, uid, c.permissions)
        await query.message.delete()
    except Exception as e:  # noqa
        log.warning("unmute failed: %s", e)
    await query.answer("Unmuted.")
