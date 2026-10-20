"""Daily token verification through one or two shorteners."""
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from bothelpers import deep
from database import verify as vdb
from utils import sc, shorten


async def prompt(uid, pending):
    token = await vdb.create_token(uid, pending)
    url = deep(f"verify-{uid}-{token}")
    url = await shorten(url, info.VERIFY_SHORTLINK_URL, info.VERIFY_SHORTLINK_API)
    if info.VERIFY_SECOND_SHORTNER:
        url = await shorten(url, info.VERIFY_SND_SHORTLINK_URL, info.VERIFY_SND_SHORTLINK_API)
    rows = [[InlineKeyboardButton("✅ " + sc("verify now"), url=url)]]
    if info.VERIFY_TUTORIAL:
        rows.append([InlineKeyboardButton("❓ " + sc("how to verify"), url=info.VERIFY_TUTORIAL)])
    return texts.VERIFY_NEEDED, InlineKeyboardMarkup(rows)


async def handle_return(uid, payload):
    """payload 'verify-<uid>-<token>' -> {'pending': ...} or None."""
    parts = payload.split("-", 2)
    if len(parts) != 3 or not parts[1].isdigit() or int(parts[1]) != uid or not parts[2].isalnum():
        return None
    return await vdb.consume_token(uid, parts[2])
