"""Stops banned users and disabled chats before any other handler."""
from pyrogram import Client, filters

import texts
from bothelpers import autodel
from database import groups, users


@Client.on_message(filters.private & filters.incoming, group=-5)
async def banned_user(client, message):
    if not message.from_user:
        return
    b = await users.ban_status(message.from_user.id)
    if b.get("on"):
        m = await message.reply_text(texts.BANNED.format(reason=b.get("reason", "")), quote=True)
        await autodel(m)
        message.stop_propagation()


@Client.on_message(filters.group & filters.incoming, group=-5)
async def disabled_group(client, message):
    if await groups.is_disabled(message.chat.id):
        g = await groups.get(message.chat.id)
        try:
            await message.reply_text(f"This chat is disabled. Reason: {(g or {}).get('disabled', {}).get('reason', '')}")
            await client.leave_chat(message.chat.id)
        except Exception:  # noqa
            pass
        message.stop_propagation()
