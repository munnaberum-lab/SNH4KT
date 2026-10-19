"""Manual (per group) filters: commands and the matcher that runs before auto filter."""
import re

from pyrogram import Client, enums, filters

import info
from bothelpers import autodel, group_admin
from database import connections, filters as fdb, gfilters as gdb
from plugins.settings import resolve_chat


async def build_reply(message):
    """Reply text and optional media from the replied message or the command text."""
    r = message.reply_to_message
    parts = message.text.split(None, 2)
    if r:
        if len(parts) < 2:
            return None
        keyword = parts[1]
        media = None
        for attr in ("photo", "video", "document", "audio", "animation", "sticker"):
            if getattr(r, attr, None):
                media = getattr(r, attr).file_id
        text = (r.caption.html if r.caption else (r.text.html if r.text else "")) or ""
        return keyword, text, media
    if len(parts) < 3:
        return None
    return parts[1], parts[2], None


async def send_filter(client, message, doc):
    if doc.get("media"):
        m = await client.send_cached_media(message.chat.id, doc["media"], caption=doc.get("reply") or "", reply_to_message_id=message.id)
    else:
        m = await message.reply_text(doc.get("reply") or "…", quote=True)
    await autodel(m)


@Client.on_message(filters.text & filters.incoming & ~filters.regex(r"^[/#]"), group=0)
async def match(client, message):
    if not message.from_user or message.chat.type == enums.ChatType.PRIVATE:
        return
    text = message.text.lower()
    candidates = [(await fdb.keywords(message.chat.id), lambda k: fdb.get(message.chat.id, k)),
                  (await gdb.keywords(), gdb.get)]
    for kws, getter in candidates:
        for kw in sorted(kws, key=len, reverse=True):
            if re.search(rf"(?:^|\W){re.escape(kw)}(?:$|\W)", text):
                doc = await getter(kw)
                if doc:
                    await send_filter(client, message, doc)
                    message.stop_propagation()


@Client.on_message(filters.command("filter"))
async def add_filter(client, message):
    chat = await resolve_chat(message)
    if not chat or not await group_admin(client, chat, message.from_user.id):
        return await message.reply_text("Group admins only (use it in the group or connect it first).")
    built = await build_reply(message)
    if not built:
        return await message.reply_text("Usage: /filter keyword reply text   (or reply to a message with /filter keyword)")
    await fdb.add(chat, built[0], built[1], media=built[2])
    await message.reply_text(f"✅ Filter <code>{built[0]}</code> saved.")


@Client.on_message(filters.command(["filters", "viewfilters"]))
async def list_filters(client, message):
    chat = await resolve_chat(message)
    kws = await fdb.keywords(chat) if chat else []
    await message.reply_text("Filters:\n" + "\n".join(f"• <code>{k}</code>" for k in kws) if kws else "No filters.")


@Client.on_message(filters.command("del"))
async def del_filter(client, message):
    chat = await resolve_chat(message)
    if not chat or not await group_admin(client, chat, message.from_user.id) or len(message.command) < 2:
        return await message.reply_text("Usage: /del keyword (group admins)")
    n = await fdb.delete(chat, message.command[1])
    await message.reply_text("Deleted." if n else "No such filter.")


@Client.on_message(filters.command("delall"))
async def del_all(client, message):
    chat = await resolve_chat(message)
    if not chat or not await group_admin(client, chat, message.from_user.id):
        return await message.reply_text("Group admins only.")
    await message.reply_text(f"Deleted {await fdb.delete_all(chat)} filters.")
