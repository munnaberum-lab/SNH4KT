"""Owner panel inside the bot: free/premium rules, quotas, new account trial, premium-only videos."""
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import info
from database import files
from utils import valid_sid

log = logging.getLogger("panel")
A = filters.user(info.ADMINS)
LABELS = {
    "premium_mode": "Premium mode (off = everything free)", "require_login": "Website needs login to play",
    "free_watch_per_day": "Free videos to watch per day (0 = unlimited)", "free_get_per_day": "Free downloads per day (0 = unlimited)",
    "new_account_trial_days": "Free premium days for new accounts", "default_new_premium": "New videos start premium-only",
}


async def render():
    c = await config.get(fresh=True)
    lines = ["<b>⚙️ Owner panel</b>", ""]
    rows = []
    for k, label in LABELS.items():
        typ = config.SCHEMA[k][1]
        if typ is bool:
            lines.append(f"{'✅' if c[k] else '❌'} {label}")
            rows.append([InlineKeyboardButton(f"{'✅' if c[k] else '❌'} {label}"[:60], callback_data=f"cfg#t#{k}")])
        else:
            lines.append(f"🔢 {label}: <b>{c[k]}</b>")
            rows.append([InlineKeyboardButton("−5", callback_data=f"cfg#d#{k}#-5"), InlineKeyboardButton("−1", callback_data=f"cfg#d#{k}#-1"),
                         InlineKeyboardButton(f"{k.replace('_', ' ')[:18]}: {c[k]}", callback_data="cfg#n"),
                         InlineKeyboardButton("+1", callback_data=f"cfg#d#{k}#1"), InlineKeyboardButton("+5", callback_data=f"cfg#d#{k}#5")])
    lines += ["", "Premium-only videos: /lock &lt;id&gt;, /unlock &lt;id&gt;, /lockall on|off (or use the website admin panel).",
              "Give premium: /add_premium &lt;user_id&gt; 1month"]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


@Client.on_message(filters.command("panel") & A)
async def panel(client, message):
    text, markup = await render()
    await message.reply_text(text, reply_markup=markup, quote=True)


@Client.on_callback_query(filters.regex(r"^cfg#"))
async def cfg_cb(client, query):
    if query.from_user.id not in info.ADMINS:
        return await query.answer("Owner only.", show_alert=True)
    parts = query.data.split("#")
    if parts[1] == "n":
        return await query.answer()
    c = await config.get(fresh=True)
    key = parts[2]
    try:
        if parts[1] == "t":
            await config.update({key: not c[key]})
        else:
            await config.update({key: max(config.SCHEMA[key][2], min(config.SCHEMA[key][3], c[key] + int(parts[3])))})
    except (ValueError, KeyError) as e:
        return await query.answer(str(e), show_alert=True)
    text, markup = await render()
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa
        pass
    await query.answer("Saved")


@Client.on_message(filters.command("setcfg") & A)
async def setcfg(client, message):
    args = message.command[1:]
    if len(args) != 2:
        return await message.reply_text("Usage: /setcfg <name> <value>\nNames: " + ", ".join(config.SCHEMA))
    try:
        await config.update({args[0]: args[1]})
    except ValueError as e:
        return await message.reply_text(f"❌ {e}")
    await message.reply_text("✅ Saved. Open /panel to see it.")


@Client.on_message(filters.command(["lock", "unlock"]) & A)
async def lock(client, message):
    sid = message.command[1] if len(message.command) > 1 else ""
    if not valid_sid(sid):
        return await message.reply_text("Usage: /lock <video id>  (the 10 character id from the website link)")
    doc = await files.get_by_sid(sid)
    if not doc:
        return await message.reply_text("Video not found.")
    value = message.command[0].split("@")[0] == "lock"
    await files.update(doc["_id"], {"premium": value})
    await message.reply_text("🔒 Premium only." if value else "🔓 Free for everyone.")


@Client.on_message(filters.command("lockall") & A)
async def lockall(client, message):
    arg = (message.command[1] if len(message.command) > 1 else "").lower()
    if arg not in ("on", "off"):
        return await message.reply_text("Usage: /lockall on  or  /lockall off")
    n = await files.set_premium(None, arg == "on")
    await message.reply_text(f"{'🔒' if arg == 'on' else '🔓'} Updated {n} videos.")
