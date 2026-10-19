"""Referral links and rewards."""
import logging

from pyrogram import Client, enums, filters

import info
import texts
from bothelpers import deep, say
from database import referrals, users

log = logging.getLogger("referral")


async def on_start(client, user, payload, is_new):
    """ref-<owner uid>: counts only for brand new users; reward triggers once per REFERRAL_COUNT."""
    if not info.PREMIUM_AND_REFERRAL_MODE or not is_new:
        return
    owner = payload[4:]
    if not owner.isdigit() or int(owner) == user.id or not await users.get(int(owner)):
        return
    if await referrals.add_referral(int(owner), user.id):
        try:
            await client.send_message(int(owner), texts.REFERRAL_DONE.format(reward=info.REFERRAL_PREMIUM_TIME))
        except Exception as e:  # noqa
            log.info("cannot notify referrer: %s", e)


async def info_text(uid):
    return texts.REFERRAL_INFO.format(link=deep(f"ref-{uid}"), count=info.REFERRAL_COUNT, reward=info.REFERRAL_PREMIUM_TIME,
                                      have=await referrals.count(uid))


@Client.on_message(filters.command(["refer", "referral"]) & filters.private)
async def refer_cmd(client, message):
    if not info.PREMIUM_AND_REFERRAL_MODE:
        return
    await say(client, message.chat.id, await info_text(message.from_user.id))


@Client.on_callback_query(filters.regex(r"^refer$"))
async def refer_cb(client, query):
    await query.answer()
    if info.PREMIUM_AND_REFERRAL_MODE:
        await say(client, query.message.chat.id, await info_text(query.from_user.id))
