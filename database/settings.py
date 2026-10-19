"""Global key-values and the heartbeat."""
from database import core
from utils import utcnow


async def get(key, default=None):
    d = await core.col("settings").find_one({"_id": key})
    return d["value"] if d else default


async def set(key, value):  # noqa: A001
    await core.col("settings").update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)


async def beat():
    await core.col("heartbeat").update_one({"_id": "main"}, {"$set": {"at": utcnow()}}, upsert=True)


async def last_beat():
    d = await core.col("heartbeat").find_one({"_id": "main"})
    return d["at"] if d else None
