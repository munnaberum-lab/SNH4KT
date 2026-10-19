"""/index with progress, cancel, resume, skip and admin approval."""
import asyncio
import logging
import re

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from bothelpers import link_from_text, send_log
from database import jobs, settings
from ingest import ingest
from utils import TTLCache

log = logging.getLogger("index")
AWAIT = TTLCache(maxsize=200, ttl=600)
CANCEL = set()
BATCH = 200


def _markup(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


@Client.on_message(filters.command("index") & filters.private)
async def index_cmd(client, message):
    AWAIT.set(message.from_user.id, True)
    await message.reply_text(texts.INDEX_ASK)


@Client.on_message(filters.command("setskip") & filters.user(info.ADMINS))
async def setskip(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text("Usage: /setskip <number of messages to skip>")
    await settings.set("index_skip", int(message.command[1]))
    await message.reply_text("✅ The next /index will skip the first messages.")


def _forward_chat(m):
    chat = getattr(m, "forward_from_chat", None) or getattr(getattr(m, "forward_origin", None), "chat", None)
    mid = getattr(m, "forward_from_message_id", None) or getattr(getattr(m, "forward_origin", None), "message_id", None)
    return (chat.id, mid) if chat and mid else None


@Client.on_message(filters.private & filters.incoming & ~filters.command(["index", "setskip"]) & (filters.forwarded | filters.regex(r"t\.me/")), group=2)
async def got_target(client, message):
    uid = message.from_user.id
    if not AWAIT.get(uid):
        return
    target = _forward_chat(message) if message.forward_date else link_from_text(message.text or "")
    if not target:
        return await message.reply_text("I could not read that. Send a message link or forward the last message.")
    chat_ref, last_id = target
    try:
        chat = await client.get_chat(chat_ref)
        msg = await client.get_messages(chat.id, last_id)
        if getattr(msg, "empty", False):
            raise ValueError("empty")
    except Exception as e:  # noqa
        name = type(e).__name__
        hint = "Make me an admin of that channel, then try again." if name in ("ChannelInvalid", "ChannelPrivate", "ChatAdminRequired", "PeerIdInvalid") else "Check the link and try again."
        return await message.reply_text(f"❌ I cannot read that message ({name}). {hint}")
    AWAIT.pop(uid)
    if uid in info.ADMINS:
        return await message.reply_text(f"Index <b>{chat.title}</b> up to message <code>{last_id}</code>?",
                                        reply_markup=_markup([[("✅ Yes", f"idx#y#{chat.id}#{last_id}"), ("✖ Cancel", "idx#n")]]))
    await client.send_message(info.INDEX_REQ_CHANNEL, f"#IndexRequest\n\nBy: {message.from_user.mention}\nChat: {chat.title} <code>{chat.id}</code>\nLast message: <code>{last_id}</code>",
                              reply_markup=_markup([[("✅ Accept", f"idx#a#{chat.id}#{last_id}#{uid}"), ("✖ Reject", f"idx#r#{uid}")]]))
    await message.reply_text("✅ Sent to the owner for approval.")


@Client.on_callback_query(filters.regex(r"^idx#"))
async def idx_cb(client, query):
    parts = query.data.split("#")
    act = parts[1]
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Only the owner can use this.", show_alert=True)
    if act == "n":
        return await query.message.edit_text("Cancelled.")
    if act == "r":
        await query.message.edit_text("Rejected.")
        try:
            await client.send_message(int(parts[2]), "Your index request was rejected.")
        except Exception:  # noqa
            pass
        return
    if act == "c":
        CANCEL.add(parts[2])
        return await query.answer("Cancelling…")
    chat, last = int(parts[2]), int(parts[3])
    if act == "a":
        try:
            await client.send_message(int(parts[4]), "✅ Your index request was accepted.")
        except Exception:  # noqa
            pass
    await query.answer()
    skip = int(await settings.get("index_skip", 0))
    await settings.set("index_skip", 0)
    jid = await jobs.create(chat, last, skip)
    status = await query.message.edit_text("Starting…", reply_markup=_markup([[("✖ Cancel", f"idx#c#{jid}")]]))
    asyncio.create_task(run_job(client, jid, status))


async def run_job(client, jid, status=None):
    job = await jobs.get(jid)
    if not job:
        return
    chat, last = job["chat"], job["last_id"]
    pos = job.get("pos", job.get("skip", 0))
    counts = {"saved": job["saved"], "dupes": job["dupes"], "errors": job["errors"], "skipped": job["skipped"]}
    total, last_edit, state = job.get("done", 0), 0.0, "done"
    loop = asyncio.get_event_loop()
    while pos < last:
        if jid in CANCEL:
            state = "cancelled"
            break
        ids = list(range(pos + 1, min(pos + BATCH, last) + 1))
        try:
            msgs = await client.get_messages(chat, ids)
        except Exception as e:  # noqa
            if type(e).__name__ == "FloodWait":
                await asyncio.sleep(int(getattr(e, "value", 5)) + 1)
                continue
            log.warning("index read failed: %s", e)
            counts["errors"] += len(ids)
            pos = ids[-1]
            continue
        for m in msgs:
            total += 1
            if not m or getattr(m, "empty", False):
                counts["skipped"] += 1
                continue
            r = await ingest(m, "channel")
            key = {"saved": "saved", "duplicate": "dupes", "skipped": "skipped"}.get(r, "errors")
            counts[key] += 1
        pos = ids[-1]
        await jobs.update(jid, {"pos": pos, "done": total, **counts})
        if status and loop.time() - last_edit > 20:
            last_edit = loop.time()
            try:
                await status.edit_text(texts.INDEX_PROGRESS.format(total=total, **counts), reply_markup=_markup([[("✖ Cancel", f"idx#c#{jid}")]]))
            except Exception:  # noqa
                pass
    CANCEL.discard(jid)
    await jobs.update(jid, {"state": state, "pos": pos, **counts})
    report = texts.INDEX_DONE.format(total=total, **counts) + ("\n(cancelled)" if state == "cancelled" else "")
    if status:
        try:
            await status.edit_text(report)
        except Exception:  # noqa
            pass
    await send_log(client, f"#Index chat <code>{chat}</code>\n{report}")


async def resume_jobs(client):
    """Called at startup: unfinished jobs continue where they stopped."""
    for j in await jobs.running():
        log.info("resuming index job %s at %s", j["_id"], j.get("pos"))
        asyncio.create_task(run_job(client, j["_id"], None))
