"""Delete tools: /delete, /deleteall, /deletefiles, DELETE_CHANNELS."""
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
from database import files
from stream import routes, thumbs
from utils import esc

log = logging.getLogger("delete")
A = filters.user(info.ADMINS)
MEDIA = filters.video | filters.document | filters.audio


def _unique_id(msg):
    for a in ("video", "document", "audio"):
        m = getattr(msg, a, None)
        if m:
            return m.file_unique_id
    return None


async def remove_record(uid_):
    """Delete the record. Returns the old doc (or None)."""
    doc = await files.get(uid_)
    if doc:
        await files.delete_ids([uid_])
        thumbs.cache_drop(doc.get("sid", ""))
        routes.forget(doc.get("sid", ""))
    return doc


@Client.on_message(filters.command("delete") & A)
async def delete_cmd(client, message):
    r = message.reply_to_message
    uid_ = _unique_id(r) if r else None
    if not uid_:
        return await message.reply_text("Reply to the file you want to remove from the database.")
    doc = await remove_record(uid_)
    if not doc:
        return await message.reply_text("That file is not in the database.")
    rows = []
    if doc.get("bin"):
        rows = [[InlineKeyboardButton("🗑 Also delete stream copy", callback_data=f"dsc#{doc['bin']}#{doc.get('thumb', 0)}")]]
    await message.reply_text("✅ Removed from the database and hidden from the website.", reply_markup=InlineKeyboardMarkup(rows) if rows else None)


@Client.on_callback_query(filters.regex(r"^dsc#"))
async def delete_stream_copy(client, query):
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Owner only.", show_alert=True)
    _, b, t = query.data.split("#")
    ids = [int(b)] + ([int(t)] if t != "0" else [])
    try:
        await client.delete_messages(info.BIN_CHANNEL, ids)
        await query.message.edit_text("✅ Removed, stream copy deleted.")
    except Exception as e:  # noqa
        await query.answer(f"Failed: {type(e).__name__}", show_alert=True)


@Client.on_message(filters.command("deleteall") & A)
async def deleteall_cmd(client, message):
    n = await files.total_count()
    await message.reply_text(f"⚠️ Delete all <b>{n}</b> files from the database?",
                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes, delete all", callback_data="dall#y"), InlineKeyboardButton("✖ No", callback_data="dall#n")]]))


@Client.on_callback_query(filters.regex(r"^dall#"))
async def deleteall_cb(client, query):
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Owner only.", show_alert=True)
    if query.data.endswith("n"):
        return await query.message.edit_text("Cancelled.")
    await query.message.edit_text(f"✅ Deleted {await files.delete_all()} files.")


@Client.on_message(filters.command("deletefiles") & A)
async def deletefiles_cmd(client, message):
    parts = message.text.split(None, 1)
    kw = parts[1].strip()[:40] if len(parts) > 1 else ""
    if not kw:
        return await message.reply_text("Usage: /deletefiles <keyword>  (for example cam)")
    n = await files.count_keyword(kw)
    if not n:
        return await message.reply_text("No files match.")
    await message.reply_text(f"⚠️ <b>{n}</b> files match <code>{esc(kw)}</code>. Delete them?",
                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Delete", callback_data=f"dkw#y#{kw}"), InlineKeyboardButton("✖ No", callback_data="dkw#n")]]))


@Client.on_callback_query(filters.regex(r"^dkw#"))
async def deletefiles_cb(client, query):
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Owner only.", show_alert=True)
    parts = query.data.split("#", 2)
    if parts[1] == "n":
        return await query.message.edit_text("Cancelled.")
    await query.message.edit_text(f"✅ Deleted {await files.delete_keyword(parts[2])} files.")


@Client.on_message(filters.chat(info.DELETE_CHANNELS) & MEDIA)
async def delete_by_forward(client, message):
    uid_ = _unique_id(message)
    if uid_ and await remove_record(uid_):
        log.info("deleted %s through the delete channel", uid_)
