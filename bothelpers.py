"""Shared helpers for plugins (not a plugin itself)."""
import logging

import info
import state
from database import autodelete
from utils import esc

log = logging.getLogger("bot")


def is_owner_admin(uid):
    return uid in info.ADMINS


def mention(user):
    if not user:
        return "Unknown"
    name = esc(((user.first_name or "") + " " + (user.last_name or "")).strip() or "User")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def deep(payload):
    return f"https://t.me/{state.bot_username}?start={payload}"


def is_channel(msg):
    t = getattr(getattr(msg, "chat", None), "type", None)
    return str(getattr(t, "name", t)).upper().endswith("CHANNEL")


async def autodel(msg, seconds=None, force=False):
    """Queue a bot message for deletion (persistent). Never in channels."""
    if msg is None or (not info.AUTO_DELETE and not force) or is_channel(msg):
        return
    try:
        await autodelete.add(msg.chat.id, msg.id, seconds or info.AUTO_DELETE_SECONDS)
    except Exception as e:  # noqa
        log.warning("autodelete queue failed: %s", e)


async def reply(message, text, seconds=None, **kw):
    m = await message.reply_text(text, quote=kw.pop("quote", True), **kw)
    await autodel(m, seconds)
    return m


async def send_log(client, text, **kw):
    if not info.LOG_CHANNEL:
        return
    try:
        await client.send_message(info.LOG_CHANNEL, text, **kw)
    except Exception as e:  # noqa
        log.warning("log channel send failed: %s", e)


async def group_admin(client, chat_id, uid):
    if uid in info.ADMINS:
        return True
    try:
        m = await client.get_chat_member(chat_id, uid)
        return str(m.status.name) in ("OWNER", "ADMINISTRATOR")
    except Exception:  # noqa
        return False


def link_from_text(text):
    """t.me/c/<id>/<msg> or t.me/<name>/<msg> -> (chat, msg_id) or None."""
    import re
    m = re.search(r"t\.me/c/(\d+)/(\d+)", text or "")
    if m:
        return int("-100" + m.group(1)), int(m.group(2))
    m = re.search(r"t\.me/([A-Za-z0-9_]{4,})/(\d+)", text or "")
    if m:
        return m.group(1), int(m.group(2))
    return None


async def say(client, chat_id, text, markup=None, seconds=None, **kw):
    """Send a bot message and queue it for auto delete."""
    m = await client.send_message(chat_id, text, reply_markup=markup, **kw)
    await autodel(m, seconds)
    return m
