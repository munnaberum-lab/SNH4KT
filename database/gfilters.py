"""Global filters (all groups)."""
from database import core


def _c():
    return core.col("gfilters")


async def add(text, reply, buttons=None, media=None):
    await _c().update_one({"text": text.lower()}, {"$set": {"reply": reply, "buttons": buttons or [], "media": media}}, upsert=True)


async def get(text):
    return await _c().find_one({"text": text.lower()})


async def keywords():
    return [d["text"] async for d in _c().find({})]


async def delete(text):
    return (await _c().delete_one({"text": text.lower()})).deleted_count


async def delete_all():
    return (await _c().delete_many({})).deleted_count
