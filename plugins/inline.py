"""Inline search: @bot name."""
import logging

from pyrogram import Client
from pyrogram.types import InlineQueryResultCachedDocument

import info
from database import files, users
from plugins import fsub
from utils import clean_query, human_size

log = logging.getLogger("inline")


async def _answer(query, results, **kw):
    try:
        await query.answer(results, **kw)
    except TypeError:  # fork without switch_pm arguments
        kw.pop("switch_pm_text", None)
        kw.pop("switch_pm_parameter", None)
        await query.answer(results, **kw)


@Client.on_inline_query()
async def inline(client, query):
    uid = query.from_user.id
    if (await users.ban_status(uid)).get("on"):
        return await _answer(query, [], cache_time=5, switch_pm_text="You are banned", switch_pm_parameter="start")
    if await fsub.check(client, uid):
        return await _answer(query, [], cache_time=5, switch_pm_text="Join the channel first", switch_pm_parameter="start")
    q = clean_query(query.query)
    if not q:
        return await _answer(query, [], cache_time=5, switch_pm_text="Type a name to search", switch_pm_parameter="start")
    offset = int(query.offset or 0)
    docs, nxt, total = await files.search(q, offset, 50)
    results = [InlineQueryResultCachedDocument(
        title=d.get("name", "")[:60], document_file_id=d["file_id"], description=f"{human_size(d.get('size', 0))}",
        caption=(info.CUSTOM_FILE_CAPTION.replace("{file_name}", d.get("name", "")).replace("{file_size}", human_size(d.get("size", 0)))
                 .replace("{file_caption}", d.get("caption") or ""))[:1000]) for d in docs]
    if not results:
        return await _answer(query, [], cache_time=5, switch_pm_text="No results", switch_pm_parameter="start")
    await _answer(query, results, cache_time=info.CACHE_TIME, is_personal=True, next_offset=str(nxt) if nxt != "" else "")
