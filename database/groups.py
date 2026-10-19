"""Groups and their per-group settings."""
import info
from database import core
from utils import utcnow


def defaults():
    return {
        "button": info.BUTTON_MODE, "botpm": False, "file_secure": info.PROTECT_CONTENT,
        "imdb": info.IMDB, "spell_check": info.SPELL_CHECK_REPLY, "welcome": info.MELCOW_NEW_USERS,
        "auto_delete": info.AUTO_DELETE, "auto_ffilter": info.AUTO_FFILTER, "max_btn": info.MAX_BTN,
        "template": info.IMDB_TEMPLATE, "caption": info.CUSTOM_FILE_CAPTION,
        "shortlink": info.SHORTLINK_MODE, "fsub": 0, "tutorial": info.TUTORIAL,
    }


def _c():
    return core.col("groups")


async def add_chat(chat_id, title):
    await _c().update_one({"_id": chat_id}, {"$setOnInsert": {"title": title, "added": utcnow(), "disabled": {"on": False, "reason": ""}, "settings": {}}}, upsert=True)


async def get(chat_id):
    return await _c().find_one({"_id": chat_id})


async def get_settings(chat_id):
    g = await get(chat_id)
    s = defaults()
    s.update((g or {}).get("settings", {}))
    return s


async def update_setting(chat_id, key, value):
    await _c().update_one({"_id": chat_id}, {"$set": {f"settings.{key}": value}}, upsert=True)


async def disable(chat_id, reason="No reason"):
    await _c().update_one({"_id": chat_id}, {"$set": {"disabled": {"on": True, "reason": reason}}}, upsert=True)


async def enable(chat_id):
    await _c().update_one({"_id": chat_id}, {"$set": {"disabled": {"on": False, "reason": ""}}})


async def is_disabled(chat_id):
    g = await get(chat_id)
    return (g or {}).get("disabled", {}).get("on", False)


async def delete(chat_id):
    await _c().delete_one({"_id": chat_id})


async def total():
    return await _c().count_documents({})


async def all_ids():
    return [g["_id"] async for g in _c().find({}, {"_id": 1})]


async def list_groups(limit=50):
    return [g async for g in _c().find({}).limit(limit)]
