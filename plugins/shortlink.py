"""Short link gate: the file button opens a shortened, signed bot link."""
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from bothelpers import deep
from utils import sc, from_b36, shorten, sign, to_b36


def make_payload(uid, inner):
    """inner is the original payload; it is carried through the shortener."""
    return f"slx_{to_b36(uid)}_{sign('sl', uid, inner)}_{inner}"


def parse_payload(uid, payload):
    """'slx_<uid36>_<sig>_<inner>' -> inner payload or None."""
    try:
        _, u36, sig, inner = payload.split("_", 3)
        if from_b36(u36) != uid or sig != sign("sl", uid, inner):
            return None
        return inner
    except ValueError:
        return None


async def prompt(uid, inner, settings=None):
    url = deep(make_payload(uid, inner))
    site = (settings or {}).get("shortlink_url") or info.SHORTLINK_URL
    api = (settings or {}).get("shortlink_api") or info.SHORTLINK_API
    short = await shorten(url, site, api)
    rows = [[InlineKeyboardButton("🔗 " + sc("get file"), url=short)]]
    tut = (settings or {}).get("tutorial") or info.TUTORIAL
    if (info.IS_TUTORIAL or (settings or {}).get("tutorial")) and tut:
        rows.append([InlineKeyboardButton("❓ " + sc("how to open link"), url=tut)])
    return texts.SHORT_NEEDED, InlineKeyboardMarkup(rows)
