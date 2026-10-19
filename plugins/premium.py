"""Plans, premium admin commands and the optional one-time trial."""
from pyrogram import Client, filters

import info
import texts
from bothelpers import say
from database import users
from utils import parse_duration, utcnow


def _left(delta):
    d = delta.days
    h = delta.seconds // 3600
    return f"{d} day(s) {h} hour(s)" if d else f"{h} hour(s) {(delta.seconds % 3600) // 60} min"


async def send_plan(client, chat_id):
    from pyrogram.types import InlineKeyboardMarkup
    text = texts.PLAN.format(text=info.PAYMENT_TEXT)
    if info.PAYMENT_QR:
        try:
            m = await client.send_photo(chat_id, info.PAYMENT_QR, caption=text)
            from bothelpers import autodel
            return await autodel(m)
        except Exception:  # noqa
            pass
    await say(client, chat_id, text)


@Client.on_message(filters.command("plan") & filters.private)
async def plan(client, message):
    if info.PREMIUM_AND_REFERRAL_MODE:
        await send_plan(client, message.chat.id)


@Client.on_callback_query(filters.regex(r"^plan$"))
async def plan_cb(client, query):
    await query.answer()
    if info.PREMIUM_AND_REFERRAL_MODE:
        await send_plan(client, query.message.chat.id)


@Client.on_message(filters.command("myplan") & filters.private)
async def myplan(client, message):
    left = await users.premium_left(message.from_user.id)
    await say(client, message.chat.id, texts.MYPLAN_ON.format(left=_left(left)) if left else texts.MYPLAN_NONE)


@Client.on_message(filters.command("trial") & filters.private)
async def trial(client, message):
    delta = parse_duration(info.FREE_TRIAL_TIME)
    if not (info.PREMIUM_AND_REFERRAL_MODE and delta):
        return
    if await users.use_trial(message.from_user.id):
        await users.add_premium(message.from_user.id, delta)
        await say(client, message.chat.id, f"✅ Trial started: {info.FREE_TRIAL_TIME}")
    else:
        await say(client, message.chat.id, "You already used your free trial.")


@Client.on_message(filters.command("add_premium") & filters.user(info.ADMINS))
async def add_premium(client, message):
    args = message.command[1:]
    delta = parse_duration(args[1]) if len(args) > 1 else None
    if len(args) < 2 or not args[0].lstrip("-").isdigit() or not delta:
        return await message.reply_text("Usage: /add_premium <user_id> <1day|1week|1month>")
    until = await users.add_premium(int(args[0]), delta)
    await message.reply_text(f"✅ Premium until {until:%Y-%m-%d %H:%M} UTC")
    try:
        await client.send_message(int(args[0]), f"🎉 Premium activated for {args[1]}.")
    except Exception:  # noqa
        pass


@Client.on_message(filters.command("remove_premium") & filters.user(info.ADMINS))
async def remove_premium(client, message):
    args = message.command[1:]
    if not args or not args[0].lstrip("-").isdigit():
        return await message.reply_text("Usage: /remove_premium <user_id>")
    await users.remove_premium(int(args[0]))
    await message.reply_text("Premium removed.")
