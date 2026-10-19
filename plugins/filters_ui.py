"""Filter menus: quality, language, year, season, episode."""
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import texts
from plugins.search import SEARCH_CACHE, edit, owner_check, render
from utils import EPISODES, LANGUAGES, QUALITIES, SEASONS, years_list

FIELDS = {"quality", "lang", "year", "season", "episode"}


def options(field):
    if field == "quality":
        return [(q, q) for q in QUALITIES]
    if field == "lang":
        return [(l.capitalize(), l) for l in LANGUAGES]
    if field == "year":
        return [(str(y), str(y)) for y in years_list()[:16]]
    if field == "season":
        return [(f"S{s}", str(s)) for s in SEASONS]
    return [(e, str(int(e[1:]))) for e in EPISODES]


def menu(key, field):
    opts, rows, per = options(field), [], 4
    for i in range(0, len(opts), per):
        rows.append([InlineKeyboardButton(label, callback_data=f"ft#{key}#{field}#{val}") for label, val in opts[i:i + per]])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"nx#{key}#0")])
    return InlineKeyboardMarkup(rows)


async def _guard(query):
    key = query.data.split("#")[1]
    st = SEARCH_CACHE.get(key)
    if not st:
        await query.answer(texts.SEARCH_EXPIRED, show_alert=True)
        return None, None
    if not owner_check(st, query):
        await query.answer(texts.NOT_YOURS, show_alert=True)
        return None, None
    return key, st


@Client.on_callback_query(filters.regex(r"^fm#"))
async def open_menu(client, query):
    key, st = await _guard(query)
    if not key:
        return
    field = query.data.split("#")[2]
    if field not in FIELDS:
        return await query.answer()
    try:
        await query.message.edit_reply_markup(menu(key, field))
    except Exception:  # noqa
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^ft#"))
async def set_filter(client, query):
    key, st = await _guard(query)
    if not key:
        return
    _, _, field, value = query.data.split("#")
    if field not in FIELDS:
        return await query.answer()
    st["filters"][field] = value if field in ("quality", "lang") else int(value)
    out = await render(key, 0)
    if out[2] == 0:
        st["filters"].pop(field, None)
        return await query.answer("No files for that filter.", show_alert=True)
    await edit(query, out[0], out[1])
    await query.answer()


@Client.on_callback_query(filters.regex(r"^fc#"))
async def clear_filters(client, query):
    key, st = await _guard(query)
    if not key:
        return
    st["filters"] = {}
    out = await render(key, 0)
    await edit(query, out[0], out[1])
    await query.answer()
