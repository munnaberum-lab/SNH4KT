"""/stream: stream and download links for any file the owner sends."""
from pyrogram import Client, filters

import enrichment
import info
from bothelpers import deep
from database import files
from ingest import ingest


@Client.on_message(filters.command("stream") & filters.user(info.ADMINS))
async def stream_cmd(client, message):
    r = message.reply_to_message
    if not (r and (r.video or r.document)):
        return await message.reply_text("Reply to a video or file with /stream")
    await ingest(r, "upload")
    media = r.video or r.document
    doc = await files.get(media.file_unique_id)
    if not doc:
        return await message.reply_text("Could not save that file.")
    if doc.get("type") == "video":
        doc, _ = await enrichment.ensure_bin(client, doc)  # exactly one stream copy, reused afterwards
        enrichment.enqueue(doc["_id"])
    base = info.URL or "(set URL)"
    path = "shorts" if doc.get("kind") == "short" else "watch"
    await message.reply_text(f"Page: {base}/{path}/{doc['sid']}\nStream: {base}/stream/{doc['sid']}\nDownload: {base}/download/{doc['sid']}\nTelegram: {deep('v_' + doc['sid'])}", quote=True)
