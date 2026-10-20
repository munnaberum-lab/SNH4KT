"""Accounts: every user must create one first. The ID is final; the password can be changed. Auto login link to the website."""
import logging
from datetime import timedelta

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import info
import state
from bothelpers import autodel, deep, say, web_link
from database import accounts, users
from utils import TTLCache, esc, sc

log = logging.getLogger("account")
PENDING = TTLCache(maxsize=5000, ttl=1800)   # uid -> {"payload": str|None, "new": bool} (what to do after the account exists)
AWAIT_ID = TTLCache(maxsize=5000, ttl=600)   # uid -> True while the user types their own ID

PROMPT = ("🆔 <b>" + sc("create your account first") + "</b>\n\n"
          "<blockquote>" + sc("one account works on telegram and on the website. your id can never be changed, so choose carefully.") + "</blockquote>\n\n"
          "🎲 " + sc("auto id: we pick one for you") + "\n✍️ " + sc("my own id: you choose it"))
ASK_ID = ("✍️ <b>" + sc("send the id you want") + "</b>\n\n" + sc("3 to 20 letters, numbers or underscore. must start with a letter.") +
          "\n⚠️ " + sc("it can never be changed later."))


def prompt_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎲 " + sc("auto id"), callback_data="acct#auto"),
                                  InlineKeyboardButton("✍️ " + sc("my own id"), callback_data="acct#own")]])


def card_text(aid, pw, premium_left=None, fresh=False):
    lines = [("✅ <b>" + sc("account created!") + "</b>") if fresh else ("🆔 <b>" + sc("your account") + "</b>"), "",
             f"🆔 {sc('id')}: <code>{esc(aid)}</code>", f"🔑 {sc('password')}: <tg-spoiler>{esc(pw)}</tg-spoiler>", ""]
    if premium_left:
        lines.append(f"💎 {sc('premium left')}: <b>{premium_left}</b>")
    lines += ["⚠️ " + sc("your id never changes. you can change the password on the website or with /setpassword."),
              "👁 " + sc("only you can see this. it disappears in a few minutes. open it again with /account.")]
    return "\n".join(lines)


def card_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🌐 " + sc("open website (auto login)"), callback_data="web#open")]])


def _left(delta):
    return f"{delta.days}d {delta.seconds // 3600}h" if delta else None


def _payload(message):
    parts = (message.text or "").split(None, 1)
    if parts and parts[0].split("@")[0] == "/start" and len(parts) > 1:
        return parts[1].strip()
    return None


async def send_card(client, chat_id, uid, fresh=False):
    acc = await accounts.get(uid)
    pw = await accounts.reveal_password(uid)
    if not acc or pw is None:
        return await say(client, chat_id, "⚠️ " + sc("could not read your account. contact the owner."))
    left = await users.premium_left(uid)
    return await say(client, chat_id, card_text(acc["aid"], pw, _left(left), fresh), card_markup(), seconds=300)


async def finish(client, user, chat_id, aid, pw):
    c = await config.get()
    if c["new_account_trial_days"]:
        await users.add_premium(user.id, timedelta(days=c["new_account_trial_days"]))
    left = await users.premium_left(user.id)
    await say(client, chat_id, card_text(aid, pw, _left(left), fresh=True), card_markup(), seconds=300)
    pend = PENDING.pop(user.id) or {"payload": None, "new": False}
    from plugins import start as start_mod
    await start_mod.run_start(client, user, chat_id, pend.get("payload"), pend.get("new", False))


async def create_for(client, user, chat_id, wanted=None):
    """wanted=None -> auto ID. Returns True when created."""
    try:
        if wanted is None:
            for _ in range(8):
                try:
                    aid, pw = await accounts.create(user.id, accounts.gen_aid(), user.first_name or "")
                    break
                except accounts.AidTaken:
                    continue
            else:
                await say(client, chat_id, "⚠️ " + sc("could not make an id, try again."))
                return False
        else:
            aid, pw = await accounts.create(user.id, wanted, user.first_name or "")
    except accounts.AidTaken:
        await say(client, chat_id, "❌ " + sc("that id is taken. send another one."))
        return False
    except accounts.HasAccount:
        return True
    except ValueError as e:
        await say(client, chat_id, f"❌ {esc(e)}")
        return False
    AWAIT_ID.pop(user.id)
    await finish(client, user, chat_id, aid, pw)
    return True


# ---- the gate: nothing works without an account -------------------------------
@Client.on_message(filters.private & filters.incoming, group=-4)
async def gate_private(client, message):
    user = message.from_user
    if not user or user.id in info.ADMINS or await accounts.has_account(user.id):
        return
    text = (message.text or "").strip()
    if AWAIT_ID.get(user.id) and text and not text.startswith("/"):
        await create_for(client, user, message.chat.id, text)
        return message.stop_propagation()
    new = await users.add_user(user.id, user.first_name or "")
    payload = _payload(message)
    prev = PENDING.get(user.id) or {}
    PENDING.set(user.id, {"payload": payload or prev.get("payload"), "new": new or prev.get("new", False)})
    m = await message.reply_text(PROMPT, reply_markup=prompt_markup(), quote=True)
    await autodel(m)
    message.stop_propagation()


@Client.on_callback_query(group=-4)
async def gate_callbacks(client, query):
    uid = query.from_user.id
    if (query.data or "").startswith("acct#") or uid in info.ADMINS or await accounts.has_account(uid):
        return
    await query.answer("Create your account first: open the bot in private and send /start", show_alert=True)
    query.stop_propagation()


@Client.on_callback_query(filters.regex(r"^acct#"))
async def acct_cb(client, query):
    user, act = query.from_user, query.data.split("#")[1]
    chat_id = query.message.chat.id if query.message else user.id
    if act == "show":
        await query.answer()
        return await send_card(client, user.id, user.id) if await accounts.has_account(user.id) else await say(client, user.id, PROMPT, prompt_markup())
    if await accounts.has_account(user.id):
        return await query.answer("You already have an account. Use /account.", show_alert=True)
    if query.message and query.message.chat.type != enums.ChatType.PRIVATE:
        return await query.answer("Open me in private to create your account.", show_alert=True)
    await query.answer()
    try:
        await query.message.delete()
    except Exception:  # noqa
        pass
    if act == "auto":
        await create_for(client, user, chat_id, None)
    elif act == "own":
        AWAIT_ID.set(user.id, True)
        await say(client, chat_id, ASK_ID, seconds=600)


@Client.on_message(filters.command(["account", "myid", "me"]) & filters.private)
async def account_cmd(client, message):
    uid = message.from_user.id
    if not await accounts.has_account(uid):  # admins reach here without the gate
        return await message.reply_text(PROMPT, reply_markup=prompt_markup(), quote=True)
    await send_card(client, message.chat.id, uid)


@Client.on_message(filters.command("setpassword") & filters.private)
async def setpassword(client, message):
    uid = message.from_user.id
    new = message.command[1] if len(message.command) > 1 else ""
    try:
        await message.delete()  # do not leave the new password in the chat
    except Exception:  # noqa
        pass
    if not await accounts.has_account(uid):
        return await say(client, message.chat.id, PROMPT, prompt_markup())
    try:
        await accounts.set_password(uid, new)
    except ValueError as e:
        return await say(client, message.chat.id, f"❌ {esc(e)}\n/setpassword NewPassword123", seconds=60)
    await say(client, message.chat.id, "✅ " + sc("password changed. other website sessions were logged out. see it with /account."), seconds=120)


@Client.on_callback_query(filters.regex(r"^web#open$"))
async def open_web(client, query):
    uid = query.from_user.id
    link = await web_link(uid, "/")
    if not link:
        return await query.answer("The website address (URL) is not set.", show_alert=True)
    await query.answer()
    await say(client, uid, "🌐 <b>" + sc("tap to open the website") + "</b>\n" + sc("you will be logged in automatically."),
              InlineKeyboardMarkup([[InlineKeyboardButton("🌐 " + sc("open website"), url=link)]]), seconds=600)


@Client.on_message(filters.command(["web", "website"]) & filters.private)
async def web_cmd(client, message):
    link = await web_link(message.from_user.id, "/")
    if link:
        await say(client, message.chat.id, "🌐 <b>" + sc("tap to open the website") + "</b>", InlineKeyboardMarkup([[InlineKeyboardButton("🌐 " + sc("open website"), url=link)]]), seconds=600)
