"""Global filters (owner only). The matcher lives in manual_filters.py."""
from pyrogram import Client, filters

import info
from database import gfilters
from plugins.manual_filters import build_reply

A = filters.user(info.ADMINS)


@Client.on_message(filters.command("gfilter") & A)
async def add(client, message):
    built = await build_reply(message)
    if not built:
        return await message.reply_text("Usage: /gfilter keyword reply text (or reply to a message)")
    await gfilters.add(built[0], built[1], media=built[2])
    await message.reply_text("✅ Global filter saved.")


@Client.on_message(filters.command("gfilters") & A)
async def list_all(client, message):
    kws = await gfilters.keywords()
    await message.reply_text("Global filters:\n" + "\n".join(f"• <code>{k}</code>" for k in kws) if kws else "No global filters.")


@Client.on_message(filters.command("delg") & A)
async def delete_one(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /delg keyword")
    await message.reply_text("Deleted." if await gfilters.delete(message.command[1]) else "No such filter.")


@Client.on_message(filters.command("delallg") & A)
async def delete_all(client, message):
    await message.reply_text(f"Deleted {await gfilters.delete_all()} global filters.")
