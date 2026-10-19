"""/start and every deep link payload."""
import logging

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import state
import texts
from bothelpers import autodel, deep, mention, say, send_log
from database import groups, referrals, users
from plugins import delivery, referral, shortlink, verify
from utils import esc

log = logging.getLogger("start")


def welcome_markup():
    rows = [[InlineKeyboardButton("➕ Add me to your group", url=f"https://t.me/{state.bot_username}?startgroup=true")]]
    row = []
    if info.CHNL_LNK:
        row.append(InlineKeyboardButton("📢 Channel", url=info.CHNL_LNK))
    if info.GRP_LNK or info.SUPPORT_CHAT:
        row.append(InlineKeyboardButton("💬 Support", url=info.GRP_LNK or f"https://t.me/{info.SUPPORT_CHAT.lstrip('@')}"))
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❓ Help", callback_data="help"), InlineKeyboardButton("ℹ️ About", callback_data="about")])
    if info.PREMIUM_AND_REFERRAL_MODE:
        rows.append([InlineKeyboardButton("💎 Premium", callback_data="plan"), InlineKeyboardButton("🎁 Referral", callback_data="refer")])
    return InlineKeyboardMarkup(rows)


async def send_welcome(client, message):
    text = texts.WELCOME.format(mention=mention(message.from_user))
    if info.PICS:
        import random
        try:
            m = await message.reply_photo(random.choice(info.PICS), caption=text, reply_markup=welcome_markup(), quote=True)
            return await autodel(m)
        except Exception:  # noqa
            pass
    m = await message.reply_text(text, reply_markup=welcome_markup(), quote=True)
    await autodel(m)


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
    chat_id = message.chat.id
    if payload.startswith("ref-"):
        await referral.on_start(client, user, payload, new)
        return await send_welcome(client, message)
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
    await send_welcome(client, message)


@Client.on_callback_query(filters.regex(r"^(help|about|home)$"))
async def info_cb(client, query):
    if query.data == "help":
        text, rows = texts.HELP, [[InlineKeyboardButton("« Back", callback_data="home")]]
    elif query.data == "about":
        text, rows = texts.ABOUT.format(site=esc(info.URL or info.SITE_NAME)), [[InlineKeyboardButton("« Back", callback_data="home")]]
    else:
        text, rows = texts.WELCOME.format(mention=mention(query.from_user)), welcome_markup().inline_keyboard
    try:
        if query.message.photo:
            await query.message.edit_caption(text, reply_markup=InlineKeyboardMarkup(rows))
        else:
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except Exception:  # noqa
        pass
    await query.answer()
