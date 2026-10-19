"""Broadcast to users or groups."""
import asyncio
import logging

from pyrogram import Client, filters

import info
from database import groups, users

log = logging.getLogger("broadcast")
RUNNING = {"on": False}


async def _run(client, message, ids, label, drop):
    if not message.reply_to_message:
        return await message.reply_text(f"Reply to the message you want to send with /{label}.")
    if RUNNING["on"]:
        return await message.reply_text("A broadcast is already running.")
    RUNNING["on"] = True
    status = await message.reply_text(f"Sending to {len(ids)}…")
    ok = bad = 0
    try:
        for i, cid in enumerate(ids, 1):
            try:
                await message.reply_to_message.copy(cid)
                ok += 1
            except Exception as e:  # noqa
                name = type(e).__name__
                if name == "FloodWait":
                    await asyncio.sleep(int(getattr(e, "value", 5)) + 1)
                    try:
                        await message.reply_to_message.copy(cid)
                        ok += 1
                        continue
                    except Exception:  # noqa
                        pass
                bad += 1
                if name in ("UserIsBlocked", "InputUserDeactivated", "PeerIdInvalid", "ChatWriteForbidden"):
                    await drop(cid)
            if i % 25 == 0:
                try:
                    await status.edit_text(f"Sent {ok}, failed {bad}, left {len(ids) - i}")
                except Exception:  # noqa
                    pass
            await asyncio.sleep(0.05)
    finally:
        RUNNING["on"] = False
    await status.edit_text(f"✅ Done. Sent {ok}, failed {bad}.")


async def _drop_user(uid):
    pass  # keep the record; the user may come back


@Client.on_message(filters.command("broadcast") & filters.user(info.ADMINS))
async def broadcast(client, message):
    await _run(client, message, await users.all_ids(), "broadcast", _drop_user)


@Client.on_message(filters.command("grp_broadcast") & filters.user(info.ADMINS))
async def grp_broadcast(client, message):
    await _run(client, message, await groups.all_ids(), "grp_broadcast", groups.delete)
