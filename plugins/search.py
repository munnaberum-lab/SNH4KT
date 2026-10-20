"""Group and PM search, pagination, spell check, movie card."""
import asyncio
import logging

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
import metadata
import texts
from bothelpers import autodel, deep
from database import accounts, files, groups, users
from plugins import delivery, fsub
from utils import sc, Cooldown, TTLCache, clean_query, esc, fmt, human_size, rand_b62

log = logging.getLogger("search")
SEARCH_CACHE = TTLCache(maxsize=3000, ttl=3600)  # key -> state (size limited, expires)
_cooldown = Cooldown(info.SEARCH_COOLDOWN)
_acct_hint = Cooldown(60)


def gsuffix(chat_id):
    s = str(chat_id)
    return f"_g{s[4:]}" if s.startswith("-100") else ""


def per_page(settings):
    return max(1, info.MAX_B_TN) if settings.get("max_btn", info.MAX_BTN) else 6


async def render(key, offset=0):
    """-> (text, InlineKeyboardMarkup, total) or None when the search expired."""
    st = SEARCH_CACHE.get(key)
    if not st:
        return None
    settings = st["settings"]
    per = per_page(settings)
    docs, nxt, total = await files.search(st["q"], offset, per, **st["filters"])
    protect_pref = "filep_" if settings.get("file_secure") else "file_"
    suffix = gsuffix(st["chat"])
    rows = []
    sids = [d["sid"] for d in docs]
    if sids:
        akey = rand_b62(8)
        delivery.SEND_ALL.set(akey, {"sids": sids})
        rows.append([InlineKeyboardButton("📥 " + sc("send all"), url=deep(f"all_{akey}{suffix}"))])
    rows.append([InlineKeyboardButton("🎞 " + sc("quality"), callback_data=f"fm#{key}#quality"),
                 InlineKeyboardButton("🌐 " + sc("language"), callback_data=f"fm#{key}#lang"),
                 InlineKeyboardButton("📅 " + sc("year"), callback_data=f"fm#{key}#year")])
    rows.append([InlineKeyboardButton("📺 " + sc("season"), callback_data=f"fm#{key}#season"),
                 InlineKeyboardButton("🎬 " + sc("episode"), callback_data=f"fm#{key}#episode")])
    if st["filters"]:
        rows.append([InlineKeyboardButton("✖ " + sc("clear filters"), callback_data=f"fc#{key}")])
    lines = []
    for d in docs:
        label = f"[{human_size(d.get('size', 0))}] {d.get('title') or d.get('name', '')}"[:60]
        url = deep(f"{protect_pref}{d['sid']}{suffix}")
        if settings.get("button", info.BUTTON_MODE):
            rows.append([InlineKeyboardButton(label, url=url)])
        else:
            lines.append(f'📁 <a href="{url}">{esc(label)}</a>')
    pages = max(1, -(-total // per))
    page = offset // per + 1
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("⏪ " + sc("back"), callback_data=f"nx#{key}#{max(0, offset - per)}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if nxt != "":
        nav.append(InlineKeyboardButton(sc("next") + " ⏩", callback_data=f"nx#{key}#{nxt}"))
    if len(nav) > 1:
        rows.append(nav)
    head = texts.RESULTS_HEADER.format(total=total, query=esc(st["q"]))
    if st["filters"]:
        head += "\n🔎 " + ", ".join(f"{k}: {v}" for k, v in st["filters"].items())
    text = head + ("\n\n" + "\n".join(lines) if lines else "")
    if not docs:
        text = f"{head}\n\nNo files match these filters."
    return text, InlineKeyboardMarkup(rows), total


async def edit(query, text, markup):
    try:
        if query.message.photo:
            await query.message.edit_caption(text[:1000], reply_markup=markup)
        else:
            await query.message.edit_text(text, reply_markup=markup)
    except Exception as e:  # noqa
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            log.info("edit failed: %s", e)


def owner_check(st, query):
    return st and st["uid"] == query.from_user.id


@Client.on_message((filters.group | filters.private) & filters.text & filters.incoming, group=1)
async def on_text(client, message):
    text = (message.text or "").strip()
    if not message.from_user or text.startswith(("/", "#")) or not (2 <= len(text) <= 100):
        return
    uid = message.from_user.id
    private = message.chat.type == enums.ChatType.PRIVATE
    from plugins.index import AWAIT  # an admin is sending an index link, not a search
    if AWAIT.get(uid):
        return
    if private:
        if not info.PM_SEARCH:
            return
        settings = groups.defaults()
        await users.add_user(uid, message.from_user.first_name or "")
    else:
        settings = await groups.get_settings(message.chat.id)
        if not settings.get("auto_ffilter"):
            return
        if settings.get("fsub") and await fsub.group_block(client, message, settings["fsub"]):
            return
    q = clean_query(text)
    if not q or not _cooldown.hit(uid):
        return
    if uid not in info.ADMINS and not await accounts.has_account(uid):
        if _acct_hint.hit(uid):  # group: ask once a minute, never search for users without an account
            m = await message.reply_text("🆔 " + sc("create your account first, then search."), quote=True,
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆔 " + sc("create account"), url=deep("acct"))]]))
            await autodel(m)
        return
    if info.SUPPORT_CHAT_ID and message.chat.id == info.SUPPORT_CHAT_ID:
        _, _, total = await files.search(q, 0, 1)
        if total:
            m = await message.reply_text(f"Found {total} files for <b>{esc(q)}</b>. Search in the main group to get them.", quote=True)
            await autodel(m)
        return
    if await files.count_keyword(q) == 0:  # small typo? search the corrected words instead
        fixed = await files.fuzzy(q)
        if fixed:
            q = fixed
    key = rand_b62(8)
    SEARCH_CACHE.set(key, {"uid": uid, "q": q, "chat": message.chat.id, "filters": {}, "settings": settings})
    out = await render(key, 0)
    text_out, markup, total = out
    if total == 0:
        return await no_results(client, message, key, q, settings, private)
    secs = None if settings.get("auto_delete", info.AUTO_DELETE) else 0
    sent = None
    if settings.get("imdb") and info.TMDB_API_KEY:
        try:
            card = await asyncio.wait_for(metadata.card(q), 3)
        except Exception:  # noqa
            card = None
        if card and card.get("poster"):
            cap = (fmt(settings.get("template") or info.IMDB_TEMPLATE, **{k: esc(v) for k, v in card.items()}) + "\n\n" + text_out)[:1000]
            try:
                sent = await message.reply_photo(card["poster"], caption=cap, reply_markup=markup, quote=True)
            except Exception as e:  # noqa
                log.info("poster failed: %s", e)
    if sent is None:
        sent = await message.reply_text(text_out, reply_markup=markup, quote=True)
    if secs != 0:
        await autodel(sent)


async def no_results(client, message, key, q, settings, private):
    if not (info.NO_RESULTS_MSG and (private or settings.get("spell_check"))):
        return
    rows, st = [], SEARCH_CACHE.get(key)
    if info.AI_SPELL_CHECK and info.TMDB_API_KEY:
        sugg = await metadata.search(q, 5)
        st["sugg"] = [s["title"] for s in sugg]
        for i, s in enumerate(sugg):
            rows.append([InlineKeyboardButton(f"{s['title']} ({s['year']})"[:60], callback_data=f"sp#{key}#{i}")])
    rows.append([InlineKeyboardButton("📝 " + sc("request this"), callback_data=f"rq#{key}")])
    text = texts.NO_RESULT.format(query=esc(q)) + (f"\n\n{texts.DID_YOU_MEAN}" if len(rows) > 1 else "")
    m = await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows), quote=True)
    await autodel(m)


@Client.on_callback_query(filters.regex(r"^nx#"))
async def next_page(client, query):
    _, key, off = query.data.split("#")
    st = SEARCH_CACHE.get(key)
    if not st:
        return await query.answer(texts.SEARCH_EXPIRED, show_alert=True)
    if not owner_check(st, query):
        return await query.answer(texts.NOT_YOURS, show_alert=True)
    out = await render(key, int(off))
    await edit(query, out[0], out[1])
    await query.answer()


@Client.on_callback_query(filters.regex(r"^sp#"))
async def spell_pick(client, query):
    _, key, idx = query.data.split("#")
    st = SEARCH_CACHE.get(key)
    if not st:
        return await query.answer(texts.SEARCH_EXPIRED, show_alert=True)
    if not owner_check(st, query):
        return await query.answer(texts.NOT_YOURS, show_alert=True)
    try:
        title = st["sugg"][int(idx)]
    except (KeyError, IndexError, ValueError):
        return await query.answer(texts.SEARCH_EXPIRED, show_alert=True)
    st["q"], st["filters"] = clean_query(title), {}
    out = await render(key, 0)
    if out[2] == 0:
        return await query.answer("No files for that title yet. Use the request button.", show_alert=True)
    await edit(query, out[0], out[1])
    await query.answer()


@Client.on_callback_query(filters.regex(r"^noop$"))
async def noop(client, query):
    await query.answer()
