"""File delivery and the access gate: banned > fsub > premium > verify > short link > deliver."""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import enrichment
import info
import state
import texts
from bothelpers import autodel, say
from database import files, groups, users
from database import verify as vdb
from utils import TTLCache, b64d, fmt, human_size, valid_sid

log = logging.getLogger("delivery")
SEND_ALL = TTLCache(maxsize=2000, ttl=3600)   # key -> {"sids": [...], "gid": int|None}


def parse_payload(payload):
    """-> (kind, ref, protect, gid) or None. kind is file, all or batch."""
    if not payload or len(payload) > 64:
        return None
    gid = None
    base = payload
    if "_g" in payload and payload.rsplit("_g", 1)[1].isdigit():
        base, g = payload.rsplit("_g", 1)
        gid = int("-100" + g)
    for prefix, protect in (("filep_", True), ("file_", None), ("v_", None)):
        if base.startswith(prefix):
            ref = base[len(prefix):]
            return ("file", ref, protect, gid) if valid_sid(ref) else None
    if base.startswith("all_"):
        ref = base[4:]
        return ("all", ref, None, gid) if ref.isalnum() else None
    for prefix in ("DSTORE-", "BATCH-"):
        if base.startswith(prefix):
            return ("batch", base[len(prefix):], None, None)
    return None


def stream_markup(doc):
    if not (info.STREAM_MODE and info.URL and doc.get("type") == "video" and doc.get("sid")):
        return None
    path = "shorts" if doc.get("kind") == "short" else "watch"
    return InlineKeyboardMarkup([[InlineKeyboardButton(texts.STREAM_BTN, url=f"{info.URL}/{path}/{doc['sid']}")]])


async def send_doc(client, chat_id, doc, protect=False, caption_tpl=None):
    caption = fmt(caption_tpl or info.CUSTOM_FILE_CAPTION, file_name=doc.get("name", ""), file_size=human_size(doc.get("size", 0)),
                  file_caption=doc.get("caption") or "")
    try:
        m = await client.send_cached_media(chat_id, doc["file_id"], caption=caption, protect_content=bool(protect),
                                           reply_markup=stream_markup(doc))
    except Exception as e:  # noqa
        if type(e).__name__ == "FloodWait":
            await asyncio.sleep(int(getattr(e, "value", 3)) + 1)
            m = await client.send_cached_media(chat_id, doc["file_id"], caption=caption, protect_content=bool(protect),
                                               reply_markup=stream_markup(doc))
        else:
            log.warning("send failed for %s: %s", doc.get("_id"), e)
            await say(client, chat_id, texts.FILE_NOT_FOUND)
            return None
    await autodel(m)
    if doc.get("type") == "video" and not doc.get("bin"):
        enrichment.enqueue(doc["_id"])
    return m


async def gate(client, user, chat_id, payload, gid=None, via_short=False):
    """Runs the access checks. Returns the group settings dict (or {}) when allowed, None when a prompt was sent."""
    from plugins import fsub, shortlink, verify
    uid = user.id
    if (await users.ban_status(uid)).get("on"):
        await say(client, chat_id, texts.BANNED.format(reason=(await users.ban_status(uid)).get("reason", "")))
        return None
    blocked = await fsub.check(client, uid, payload)
    if blocked:
        await say(client, chat_id, blocked[0], blocked[1])
        return None
    settings = await groups.get_settings(gid) if gid else {}
    premium = info.PREMIUM_AND_REFERRAL_MODE and await users.is_premium(uid)
    if not premium and info.VERIFY and not await vdb.is_verified_today(uid):
        text, markup = await verify.prompt(uid, payload)
        await say(client, chat_id, text, markup)
        return None
    short_on = settings.get("shortlink") if gid else info.SHORTLINK_MODE
    if not premium and short_on and not via_short:
        text, markup = await shortlink.prompt(uid, payload, settings)
        await say(client, chat_id, text, markup)
        return None
    return settings


async def handle_payload(client, user, chat_id, payload, via_short=False):
    """Handle file_/filep_/v_/all_/DSTORE-/BATCH- payloads. Returns True when it was one of them."""
    parsed = parse_payload(payload)
    if not parsed:
        return False
    kind, ref, protect, gid = parsed
    settings = await gate(client, user, chat_id, payload, gid, via_short)
    if settings is None:
        return True
    if protect is None:
        protect = settings.get("file_secure", info.PROTECT_CONTENT) if gid else info.PROTECT_CONTENT
    caption = settings.get("caption") if gid else None
    if kind == "file":
        doc = await files.get_by_sid(ref)
        if not doc:
            await say(client, chat_id, texts.FILE_NOT_FOUND)
        else:
            await send_doc(client, chat_id, doc, protect, caption)
    elif kind == "all":
        entry = SEND_ALL.get(ref)
        if not entry:
            await say(client, chat_id, texts.SEARCH_EXPIRED)
            return True
        for sid in entry["sids"]:
            doc = await files.get_by_sid(sid)
            if doc:
                await send_doc(client, chat_id, doc, protect, caption)
                await asyncio.sleep(0.6)
    elif kind == "batch":
        await send_batch(client, chat_id, ref, protect)
    return True


async def send_batch(client, chat_id, b64, protect):
    """DSTORE payload: base64('<chat>_<first>_<last>') for channels listed in FILE_STORE_CHANNEL."""
    raw = b64d(b64)
    try:
        chat, first, last = raw.rsplit("_", 2)
        chat, first, last = int(chat), int(first), int(last)
    except (ValueError, AttributeError):
        return await say(client, chat_id, texts.FILE_NOT_FOUND)
    if chat not in info.FILE_STORE_CHANNEL or first > last or last - first > 200:
        return await say(client, chat_id, texts.FILE_NOT_FOUND)
    sent = 0
    for m in await client.get_messages(chat, list(range(first, last + 1))):
        if not m or getattr(m, "empty", False) or not (m.video or m.document or m.audio):
            continue
        try:
            c = await m.copy(chat_id, protect_content=bool(protect))
            await autodel(c)
            sent += 1
        except Exception as e:  # noqa
            if type(e).__name__ == "FloodWait":
                await asyncio.sleep(int(getattr(e, "value", 3)) + 1)
            else:
                log.warning("batch copy failed: %s", e)
        await asyncio.sleep(0.6)
    if not sent:
        await say(client, chat_id, texts.FILE_NOT_FOUND)
