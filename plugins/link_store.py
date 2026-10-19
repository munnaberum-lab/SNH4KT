"""/link (one file) and /batch (many posts) deep links."""
from pyrogram import Client, filters

import info
from bothelpers import deep, link_from_text
from ingest import ingest
from utils import b64e
import enrichment
from database import files

A = filters.user(info.ADMINS)


@Client.on_message(filters.command("link") & A)
async def link_cmd(client, message):
    r = message.reply_to_message
    if not (r and (r.video or r.document or r.audio)):
        return await message.reply_text("Reply to a file with /link")
    await ingest(r, "channel")
    media = r.video or r.document or r.audio
    doc = await files.get(media.file_unique_id)
    if not doc:
        return await message.reply_text("Could not save that file.")
    lines = [f"Bot link:\n{deep('file_' + doc['sid'])}", f"Protected:\n{deep('filep_' + doc['sid'])}"]
    if info.URL and doc.get("type") == "video":
        path = "shorts" if doc.get("kind") == "short" else "watch"
        lines.append(f"Website (after processing):\n{info.URL}/{path}/{doc['sid']}")
    await message.reply_text("\n\n".join(lines), quote=True)


@Client.on_message(filters.command("batch") & A)
async def batch_cmd(client, message):
    links = [link_from_text(x) for x in message.command[1:3]]
    if len(links) < 2 or not all(links):
        return await message.reply_text("Usage: /batch <first post link> <last post link>")
    (c1, first), (c2, last) = links
    chat = await client.get_chat(c1)
    if chat.id != (await client.get_chat(c2)).id:
        return await message.reply_text("Both links must be from the same channel.")
    if chat.id not in info.FILE_STORE_CHANNEL:
        return await message.reply_text("That channel is not listed in FILE_STORE_CHANNEL.")
    if first > last or last - first > 200:
        return await message.reply_text("The range must be 1 to 200 posts, first before last.")
    await message.reply_text(f"Batch link:\n{deep('DSTORE-' + b64e(f'{chat.id}_{first}_{last}'))}", quote=True)
