"""Manual filters per group."""
from database import core


def _c():
    return core.col("filters")


async def add(group, text, reply, buttons=None, media=None):
    await _c().update_one({"group": group, "text": text.lower()},
                          {"$set": {"reply": reply, "buttons": buttons or [], "media": media}}, upsert=True)


async def get(group, text):
    return await _c().find_one({"group": group, "text": text.lower()})


async def keywords(group):
    return [d["text"] async for d in _c().find({"group": group})]


async def delete(group, text):
    return (await _c().delete_one({"group": group, "text": text.lower()})).deleted_count


async def delete_all(group):
    return (await _c().delete_many({"group": group})).deleted_count
