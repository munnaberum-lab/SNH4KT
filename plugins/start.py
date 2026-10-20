"""/start and every deep link payload."""
import logging
import random

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import info
import state
import texts
from bothelpers import autodel, mention, say, send_log
from database import groups, users
from plugins import delivery, referral, shortlink, verify
from utils import esc, sc

log = logging.getLogger("start")


async def welcome_markup():
    c = await config.get()
    rows = []
    if info.URL:
        rows.append([InlineKeyboardButton("🌐 " + sc("open website"), callback_data="web#open"),
                     InlineKeyboardButton("🆔 " + sc("my account"), callback_data="acct#show")])
    rows.append([InlineKeyboardButton("➕ " + sc("add me to your group"), url=f"https://t.me/{state.bot_username}?startgroup=true")])
    row = []
    if info.CHNL_LNK:
        row.append(InlineKeyboardButton("📢 " + sc("channel"), url=info.CHNL_LNK))
    if info.GRP_LNK or info.SUPPORT_CHAT:
        row.append(InlineKeyboardButton("💬 " + sc("support"), url=info.GRP_LNK or f"https://t.me/{info.SUPPORT_CHAT.lstrip('@')}"))
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❓ " + sc("help"), callback_data="help"), InlineKeyboardButton("ℹ️ " + sc("about"), callback_data="about")])
    if c["premium_mode"]:
        rows.append([InlineKeyboardButton("💎 " + sc("premium"), callback_data="plan"), InlineKeyboardButton("🎁 " + sc("referral"), callback_data="refer")])
    return InlineKeyboardMarkup(rows)


async def send_welcome(client, user, chat_id):
    text = texts.WELCOME.format(mention=mention(user))
    markup = await welcome_markup()
    if info.PICS:
        try:
            m = await client.send_photo(chat_id, random.choice(info.PICS), caption=text, reply_markup=markup)
            return await autodel(m)
        except Exception:  # noqa
            pass
    await say(client, chat_id, text, markup)


async def run_start(client, user, chat_id, payload, new=False):
    """Everything /start does once the user has an account."""
    payload = payload or ""
    if payload.startswith("ref-"):
        await referral.on_start(client, user, payload, new)
        return await send_welcome(client, user, chat_id)
    if payload.startswith("verify-"):
        res = await verify.handle_return(user.id, payload)
        if not res:
            return await say(client, chat_id, texts.VERIFY_BAD)
        await say(client, chat_id, texts.VERIFY_OK)
        if res.get("pending"):
            await delivery.handle_payload(client, user, chat_id, res["pending"])
        return
    if payload.startswith("slx_"):
        inner = shortlink.parse_payload(user.id, payload)
        if not inner or not await delivery.handle_payload(client, user, chat_id, inner, via_short=True):
            return await say(client, chat_id, texts.VERIFY_BAD)
        return
    if payload and await delivery.handle_payload(client, user, chat_id, payload):
        return
    await send_welcome(client, user, chat_id)


@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    if not message.from_user:
        return
    user = message.from_user
    if message.chat.type != enums.ChatType.PRIVATE:
        await groups.add_chat(message.chat.id, message.chat.title)
        m = await message.reply_text("Send a name here to search. Open me in private for more.", quote=True)
        return await autodel(m)
    new = await users.add_user(user.id, user.first_name or "")
    if new:
        await send_log(client, texts.NEW_USER_LOG.format(id=user.id, mention=mention(user)))
    payload = message.command[1] if len(message.command) > 1 else ""
    await run_start(client, user, message.chat.id, payload, new)


@Client.on_callback_query(filters.regex(r"^(help|about|home)$"))
async def info_cb(client, query):
    back = [[InlineKeyboardButton("« " + sc("back"), callback_data="home")]]
    if query.data == "help":
        text, rows = texts.HELP, back
    elif query.data == "about":
        text, rows = texts.ABOUT.format(site=esc(info.URL or info.SITE_NAME)), back
    else:
        text, rows = texts.WELCOME.format(mention=mention(query.from_user)), (await welcome_markup()).inline_keyboard
    try:
        if query.message.photo:
            await query.message.edit_caption(text, reply_markup=InlineKeyboardMarkup(rows))
        else:
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except Exception:  # noqa
        pass
    await query.answer()
