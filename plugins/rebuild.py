"""/rebuild: refresh file_id after a bot change by scanning BIN (and BACKUP) channels."""
import asyncio
import logging

from pyrogram import Client, filters

import info
from database import files

log = logging.getLogger("rebuild")
RUNNING = {"on": False}


async def top_id(client, chat):
    probe = await client.send_message(chat, "scanning…")
    top = probe.id
    await probe.delete()
    return top


async def rebuild_channel(client, chat, status):
    top = await top_id(client, chat)
    fixed = seen = 0
    pos = top - 1
    while pos > 0:
        ids = list(range(max(1, pos - 199), pos + 1))
        try:
            msgs = await client.get_messages(chat, ids)
        except Exception as e:  # noqa
            if type(e).__name__ == "FloodWait":
                await asyncio.sleep(int(getattr(e, "value", 5)) + 1)
                continue
            raise
        for m in msgs:
            media = m and (getattr(m, "video", None) or getattr(m, "document", None))
            if not media:
                continue
            seen += 1
            from utils import pack_file_id
            doc = await files.get(media.file_unique_id)
            if doc:
                await files.update(doc["_id"], {"file_id": pack_file_id(media.file_id), "bin": m.id} if chat == info.BIN_CHANNEL else {"file_id": pack_file_id(media.file_id)})
                fixed += 1
        pos = ids[0] - 1
        try:
            await status.edit_text(f"Scanning {chat}… seen {seen}, updated {fixed}")
        except Exception:  # noqa
            pass
    return seen, fixed


@Client.on_message(filters.command("rebuild") & filters.user(info.ADMINS))
async def rebuild_cmd(client, message):
    if RUNNING["on"]:
        return await message.reply_text("A rebuild is already running.")
    RUNNING["on"] = True
    status = await message.reply_text("Starting… (the bot must be admin in these channels)")
    try:
        total = 0
        for chat in [c for c in (info.BIN_CHANNEL, info.BACKUP_CHANNEL) if c]:
            seen, fixed = await rebuild_channel(client, chat, status)
            total += fixed
        await status.edit_text(f"✅ Rebuild finished. Updated {total} records.")
    except Exception as e:  # noqa
        await status.edit_text(f"❌ Rebuild stopped: {type(e).__name__}. Is the bot admin in the channel?")
    finally:
        RUNNING["on"] = False
