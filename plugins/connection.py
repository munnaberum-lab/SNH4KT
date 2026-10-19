"""Connect a group to your PM so you can manage settings and filters from there."""
from pyrogram import Client, enums, filters

from bothelpers import group_admin
from database import connections, groups


@Client.on_message(filters.command("connect"))
async def connect(client, message):
    uid = message.from_user.id
    if message.chat.type == enums.ChatType.PRIVATE:
        args = message.command[1:]
        if not args or not args[0].lstrip("-").isdigit():
            return await message.reply_text("Usage: /connect <group id>  (or send /connect inside the group)")
        chat = int(args[0])
    else:
        chat = message.chat.id
    if not await group_admin(client, chat, uid):
        return await message.reply_text("You must be an admin of that group.")
    await groups.add_chat(chat, getattr(message.chat, "title", None) or str(chat))
    await connections.add(uid, chat)
    await message.reply_text("✅ Connected. Manage it from my PM with /settings and /filter.")


@Client.on_message(filters.command("disconnect"))
async def disconnect(client, message):
    chat = await connections.active(message.from_user.id) if message.chat.type == enums.ChatType.PRIVATE else message.chat.id
    if chat:
        await connections.remove(message.from_user.id, chat)
    await message.reply_text("Disconnected.")


@Client.on_message(filters.command("connections") & filters.private)
async def list_connections(client, message):
    gs = await connections.groups(message.from_user.id)
    if not gs:
        return await message.reply_text("No connected groups.")
    lines = []
    for g in gs:
        doc = await groups.get(g)
        lines.append(f"• {(doc or {}).get('title', g)} <code>{g}</code>")
    await message.reply_text("\n".join(lines))
