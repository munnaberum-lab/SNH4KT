"""/enrich (upgrade old indexed files) and /thumb <sid>."""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import enrichment
import info
import texts
from database import files
from utils import valid_sid

log = logging.getLogger("enrich")
A = filters.user(info.ADMINS)


@Client.on_message(filters.command("enrich") & A)
async def enrich_cmd(client, message):
    before = dict(enrichment.progress)
    queued = await enrichment.enqueue_pending()
    if not queued:
        return await message.reply_text("Nothing to enrich. Every video already has a stream copy.")
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✖ Cancel", callback_data="enr#c")]])
    status = await message.reply_text(f"Queued {queued} videos…", reply_markup=markup)
    base_done, base_failed = before["done"], before["failed"]
    while True:
        await asyncio.sleep(5)
        p = enrichment.progress
        done, failed = p["done"] - base_done, p["failed"] - base_failed
        try:
            await status.edit_text(texts.ENRICH_PROGRESS.format(done=done, total=queued, failed=failed), reply_markup=markup)
        except Exception:  # noqa
            pass
        if done + failed >= queued:
            break
    await status.edit_text(f"✅ Enrich finished. Done {done}, failed {failed}.")


@Client.on_callback_query(filters.regex(r"^enr#c$"))
async def enrich_cancel(client, query):
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Owner only.", show_alert=True)
    n = enrichment.cancel_all()
    await query.answer(f"Cancelled {n} queued videos.", show_alert=True)


@Client.on_message(filters.command("thumb") & A)
async def thumb_cmd(client, message):
    sid = message.command[1] if len(message.command) > 1 else ""
    r = message.reply_to_message
    if not valid_sid(sid) or not (r and r.photo):
        return await message.reply_text("Reply to a photo with /thumb <sid>")
    doc = await files.get_by_sid(sid)
    if not doc or not doc.get("bin"):
        return await message.reply_text("Video not found.")
    bio = await client.download_media(r.photo.file_id, in_memory=True)
    await enrichment.store_thumb(client, doc, bio.getvalue())
    await message.reply_text("✅ Thumbnail replaced.")
