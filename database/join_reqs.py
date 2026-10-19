"""Join requests (request-to-join force subscribe)."""
from database import core
from utils import utcnow


async def add(uid, chan):
    await core.col("join_reqs").update_one({"uid": uid, "chan": chan}, {"$setOnInsert": {"date": utcnow()}}, upsert=True)


async def has(uid, chan):
    return await core.col("join_reqs").find_one({"uid": uid, "chan": chan}) is not None


async def remove(uid, chan):
    await core.col("join_reqs").delete_many({"uid": uid, "chan": chan})


async def purge(chan=None):
    q = {"chan": chan} if chan else {}
    return (await core.col("join_reqs").delete_many(q)).deleted_count
