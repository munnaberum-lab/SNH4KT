"""#request / /request flow with admin buttons."""
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from bothelpers import autodel, mention, say
from database import requests as rdb
from plugins.search import SEARCH_CACHE
from utils import esc

log = logging.getLogger("requests")
STATUS = {"up": ("✅ Uploaded", "Your request was uploaded. Search again!"),
          "av": ("📂 Already available", "Your request is already available. Search with another spelling."),
          "un": ("❌ Unavailable", "Sorry, your request is not available.")}


async def submit(client, user, chat, text):
    text = text.strip()[:200]
    if not text:
        return False
    if not info.REQST_CHANNEL:
        return None
    rid = await rdb.add(user.id, chat.id, text)
    rows = [[InlineKeyboardButton(label, callback_data=f"rqs#{rid}#{code}")] for code, (label, _) in STATUS.items()]
    await client.send_message(info.REQST_CHANNEL, texts.REQUEST_CARD.format(mention=mention(user), uid=user.id, chat=esc(getattr(chat, "title", None) or "PM"), text=esc(text)),
                              reply_markup=InlineKeyboardMarkup(rows))
    return True


@Client.on_message(filters.text & filters.incoming & filters.regex(r"(?i)^(#request|/request)(@\w+)?(\s|$)"), group=0)
async def request_cmd(client, message):
    if not message.from_user:
        return
    text = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else ""
    res = await submit(client, message.from_user, message.chat, text)
    if res is None:
        m = await message.reply_text("Requests are not enabled.", quote=True)
    elif res is False:
        m = await message.reply_text("Usage: <code>/request movie name</code>", quote=True)
    else:
        m = await message.reply_text(texts.REQUEST_SENT, quote=True)
    await autodel(m)
    message.stop_propagation()


@Client.on_callback_query(filters.regex(r"^rq#"))
async def request_button(client, query):
    st = SEARCH_CACHE.get(query.data.split("#")[1])
    if not st:
        return await query.answer(texts.SEARCH_EXPIRED, show_alert=True)
    if st["uid"] != query.from_user.id:
        return await query.answer(texts.NOT_YOURS, show_alert=True)
    res = await submit(client, query.from_user, query.message.chat, st["q"])
    await query.answer(texts.REQUEST_SENT.replace("✅ ", "") if res else "Requests are not enabled.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^rqs#"))
async def request_status(client, query):
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Only the owner can use this.", show_alert=True)
    _, rid, code = query.data.split("#")
    req, (label, msg) = await rdb.get(rid), STATUS.get(code, STATUS["un"])
    if not req:
        return await query.answer("Request not found.", show_alert=True)
    await rdb.set_status(rid, code)
    try:
        await client.send_message(req["uid"], f"<b>{esc(req['text'])}</b>\n{msg}")
    except Exception:  # noqa
        pass
    try:
        await query.message.edit_text(query.message.text.html + f"\n\nStatus: {label}")
    except Exception:  # noqa
        pass
    await query.answer("Done")
