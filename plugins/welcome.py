"""Welcome messages and bot-added-to-group logging."""
from pyrogram import Client, filters

import state
import texts
from bothelpers import autodel, mention, send_log
from database import groups


@Client.on_message(filters.new_chat_members & filters.group)
async def on_new_members(client, message):
    for member in message.new_chat_members:
        if member.id == state.main.me.id:
            if not await groups.get(message.chat.id):
                try:
                    count = await client.get_chat_members_count(message.chat.id)
                except Exception:  # noqa
                    count = "?"
                await send_log(client, texts.NEW_GROUP_LOG.format(title=message.chat.title, id=message.chat.id, count=count,
                                                                  by=mention(message.from_user) if message.from_user else "?"))
            await groups.add_chat(message.chat.id, message.chat.title)
            continue
        s = await groups.get_settings(message.chat.id)
        if s.get("welcome"):
            m = await message.reply_text(texts.WELCOME_GROUP.format(mention=mention(member), title=message.chat.title))
            await autodel(m)
