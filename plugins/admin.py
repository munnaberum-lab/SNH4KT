"""Owner commands."""
import logging
import os
import sys

from pyrogram import Client, enums, filters

import info
import state
import texts
from database import files, groups, requests as rdb, users
from stream import clients
from utils import esc

log = logging.getLogger("admin")
A = filters.user(info.ADMINS)


def _uid_arg(message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id, " ".join(message.command[1:]) or "No reason"
    args = message.command[1:]
    if args and args[0].lstrip("-").isdigit():
        return int(args[0]), " ".join(args[1:]) or "No reason"
    return None, ""


@Client.on_message(filters.command("stats") & A)
async def stats(client, message):
    s = await files.stats()
    await message.reply_text(texts.STATS.format(files=s["files"], videos=s["videos"], shorts=s["shorts"], longs=s["longs"], users=await users.total(),
                                               groups=await groups.total(), premium=await users.premium_count(), banned=await users.banned_count(),
                                               views=s["views"], streams=clients.active_streams()))


@Client.on_message(filters.command("users") & A)
async def users_cmd(client, message):
    lines = [f"{esc(u.get('name', ''))} <code>{u['_id']}</code>" for u in await users.list_users(50)]
    await message.reply_text(f"Users: {await users.total()} (first 50)\n\n" + "\n".join(lines))


@Client.on_message(filters.command("chats") & A)
async def chats_cmd(client, message):
    lines = [f"{esc(g.get('title', ''))} <code>{g['_id']}</code>" for g in await groups.list_groups(50)]
    await message.reply_text(f"Groups: {await groups.total()} (first 50)\n\n" + "\n".join(lines))


@Client.on_message(filters.command("ban") & A)
async def ban(client, message):
    uid, reason = _uid_arg(message)
    if not uid:
        return await message.reply_text("Usage: /ban <user_id> [reason] (or reply)")
    await users.ban(uid, reason)
    await message.reply_text(f"Banned <code>{uid}</code>.")


@Client.on_message(filters.command("unban") & A)
async def unban(client, message):
    uid, _ = _uid_arg(message)
    if not uid:
        return await message.reply_text("Usage: /unban <user_id>")
    await users.unban(uid)
    await message.reply_text(f"Unbanned <code>{uid}</code>.")


def _chat_arg(message):
    args = message.command[1:]
    return (int(args[0]), " ".join(args[1:]) or "No reason") if args and args[0].lstrip("-").isdigit() else (None, "")


@Client.on_message(filters.command("leave") & A)
async def leave(client, message):
    chat, _ = _chat_arg(message)
    if not chat:
        return await message.reply_text("Usage: /leave <chat_id>")
    try:
        await client.leave_chat(chat)
        await message.reply_text("Left.")
    except Exception as e:  # noqa
        await message.reply_text(f"Failed: {esc(e)}")


@Client.on_message(filters.command("disable") & A)
async def disable(client, message):
    chat, reason = _chat_arg(message)
    if not chat:
        return await message.reply_text("Usage: /disable <chat_id> [reason]")
    await groups.disable(chat, reason)
    await message.reply_text("Chat disabled.")


@Client.on_message(filters.command("enable") & A)
async def enable(client, message):
    chat, _ = _chat_arg(message)
    if not chat:
        return await message.reply_text("Usage: /enable <chat_id>")
    await groups.enable(chat)
    await message.reply_text("Chat enabled.")


@Client.on_message(filters.command("invite") & A)
async def invite(client, message):
    chat, _ = _chat_arg(message)
    if not chat:
        return await message.reply_text("Usage: /invite <chat_id>")
    try:
        await message.reply_text(await client.export_chat_invite_link(chat))
    except Exception as e:  # noqa
        await message.reply_text(f"Failed: {esc(e)}")


@Client.on_message(filters.command("logs") & A)
async def logs(client, message):
    path = os.environ.get("LOG_FILE", "bot.log")
    if os.path.exists(path):
        await message.reply_document(path)
    else:
        await message.reply_text("No log file yet.")


@Client.on_message(filters.command("restart") & A)
async def restart(client, message):
    await message.reply_text("♻️ Restarting…")
    os.execl(sys.executable, sys.executable, *sys.argv)


@Client.on_message(filters.command("channel") & A)
async def channel(client, message):
    def line(name, v):
        return f"{name}: <code>{v}</code>" if v else f"{name}: not set"
    await message.reply_text("\n".join([line("CHANNELS", " ".join(map(str, info.CHANNELS))), line("BIN_CHANNEL", info.BIN_CHANNEL), line("LOG_CHANNEL", info.LOG_CHANNEL),
                                        line("AUTH_CHANNEL", info.AUTH_CHANNEL), line("REQST_CHANNEL", info.REQST_CHANNEL), line("BACKUP_CHANNEL", info.BACKUP_CHANNEL)]))


@Client.on_message(filters.command("id"))
async def id_cmd(client, message):
    r = message.reply_to_message
    lines = [f"Chat: <code>{message.chat.id}</code>"]
    if message.from_user:
        lines.append(f"You: <code>{message.from_user.id}</code>")
    if r and r.from_user:
        lines.append(f"Replied user: <code>{r.from_user.id}</code>")
    fwd = getattr(r, "forward_from_chat", None) if r else None
    if fwd:
        lines.append(f"Forwarded chat: <code>{fwd.id}</code>")
    await message.reply_text("\n".join(lines), quote=True)


@Client.on_message(filters.command("info") & A)
async def info_cmd(client, message):
    uid, _ = _uid_arg(message)
    if not uid:
        return await message.reply_text("Usage: /info <user_id>")
    u = await users.get(uid)
    if not u:
        return await message.reply_text("Unknown user.")
    await message.reply_text(f"ID: <code>{uid}</code>\nName: {esc(u.get('name', ''))}\nJoined: {u.get('joined')}\nBanned: {u.get('ban', {}).get('on')}\n"
                             f"Premium left: {await users.premium_left(uid)}")


@Client.on_message(filters.command("totalrequests") & A)
async def totalrequests(client, message):
    await message.reply_text(f"Requests: {await rdb.total()}")


@Client.on_message(filters.command("purgerequests") & A)
async def purgerequests(client, message):
    await message.reply_text(f"Deleted {await rdb.purge()} requests.")
