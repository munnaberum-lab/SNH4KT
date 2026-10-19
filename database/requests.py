"""#request flow records."""
from database import core
from utils import rand_b62, utcnow


def _c():
    return core.col("requests")


async def add(uid, chat, text):
    rid = rand_b62(8)
    await _c().insert_one({"_id": rid, "uid": uid, "chat": chat, "text": text, "status": "open", "date": utcnow()})
    return rid


async def get(rid):
    return await _c().find_one({"_id": rid})


async def set_status(rid, status):
    await _c().update_one({"_id": rid}, {"$set": {"status": status}})


async def total():
    return await _c().count_documents({})


async def purge():
    return (await _c().delete_many({})).deleted_count
