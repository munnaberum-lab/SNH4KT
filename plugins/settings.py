"""Per-group settings (/settings) and the /set_* commands."""
import logging

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from bothelpers import group_admin, say
from database import connections, groups
from utils import esc

log = logging.getLogger("settings")
TOGGLES = [("button", "Button mode"), ("file_secure", "Protect content"), ("imdb", "Movie card"), ("spell_check", "Spell check"),
           ("welcome", "Welcome message"), ("auto_delete", "Auto delete"), ("auto_ffilter", "Auto filter"), ("max_btn", "Max buttons"),
           ("shortlink", "Short link")]


async def resolve_chat(message):
    """Group id for commands used in a group, or the connected group in PM."""
    if message.chat.type != enums.ChatType.PRIVATE:
        return message.chat.id
    return await connections.active(message.from_user.id)


async def panel(chat_id):
    s = await groups.get_settings(chat_id)
    g = await groups.get(chat_id)
    rows = [[InlineKeyboardButton(f"{'✅' if s.get(k) else '❌'} {label}", callback_data=f"st#{chat_id}#{k}")] for k, label in TOGGLES]
    return texts.SETTINGS_TITLE.format(title=esc((g or {}).get("title", str(chat_id)))), InlineKeyboardMarkup(rows)


@Client.on_message(filters.command("settings"))
async def settings_cmd(client, message):
    chat_id = await resolve_chat(message)
    if not chat_id:
        return await message.reply_text("Connect a group first with /connect in that group.")
    if not await group_admin(client, chat_id, message.from_user.id):
        return await message.reply_text("Only group admins can change settings.")
    text, markup = await panel(chat_id)
    await message.reply_text(text, reply_markup=markup, quote=True)


@Client.on_callback_query(filters.regex(r"^st#"))
async def toggle(client, query):
    _, chat, key = query.data.split("#")
    chat = int(chat)
    if key not in dict(TOGGLES):
        return await query.answer()
    if not await group_admin(client, chat, query.from_user.id):
        return await query.answer("Only group admins can change settings.", show_alert=True)
    s = await groups.get_settings(chat)
    await groups.update_setting(chat, key, not s.get(key))
    text, markup = await panel(chat)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa
        pass
    await query.answer("Saved")


async def _admin_chat(client, message):
    chat_id = await resolve_chat(message)
    if not chat_id or not await group_admin(client, chat_id, message.from_user.id):
        await message.reply_text("Use this in a group you administer (or connect it first).")
        return None
    return chat_id


def _arg(message):
    parts = message.text.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


@Client.on_message(filters.command("set_shortlink"))
async def set_shortlink(client, message):
    chat = await _admin_chat(client, message)
    args = _arg(message).split()
    if not chat or len(args) != 2:
        return None if not chat else await message.reply_text("Usage: /set_shortlink <site> <api key>")
    await groups.update_setting(chat, "shortlink_url", args[0])
    await groups.update_setting(chat, "shortlink_api", args[1])
    await groups.update_setting(chat, "shortlink", True)
    await message.reply_text("✅ Short link saved and turned on.")
    try:
        await message.delete()  # the message holds an API key
    except Exception:  # noqa
        pass


@Client.on_message(filters.command("set_fsub"))
async def set_fsub(client, message):
    chat = await _admin_chat(client, message)
    arg = _arg(message)
    if not chat:
        return
    if arg.lower() == "off":
        await groups.update_setting(chat, "fsub", 0)
        return await message.reply_text("Force subscribe turned off.")
    if not arg.lstrip("-").isdigit():
        return await message.reply_text("Usage: /set_fsub <channel id> or /set_fsub off")
    await groups.update_setting(chat, "fsub", int(arg))
    await message.reply_text("✅ Force subscribe set. Make me admin in that channel.")


@Client.on_message(filters.command(["set_caption", "set_template", "set_tutorial"]))
async def set_text(client, message):
    chat = await _admin_chat(client, message)
    arg = _arg(message)
    if not chat:
        return
    key = {"set_caption": "caption", "set_template": "template", "set_tutorial": "tutorial"}[message.command[0].split("@")[0]]
    if not arg:
        return await message.reply_text(f"Usage: /{message.command[0]} <value>")
    await groups.update_setting(chat, key, arg)
    await message.reply_text("✅ Saved.")
