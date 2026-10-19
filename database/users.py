"""Users, bans and premium."""
from datetime import timedelta

from database import core
from utils import utcnow


def _c():
    return core.col("users")


async def add_user(uid, name):
    """Returns True if the user is new."""
    r = await _c().update_one({"_id": uid}, {"$setOnInsert": {"name": name, "joined": utcnow(), "ban": {"on": False, "reason": ""}}}, upsert=True)
    return r.upserted_id is not None


async def get(uid):
    return await _c().find_one({"_id": uid})


async def is_new(uid):
    return await get(uid) is None


async def ban(uid, reason="No reason"):
    await _c().update_one({"_id": uid}, {"$set": {"ban": {"on": True, "reason": reason}}}, upsert=True)


async def unban(uid):
    await _c().update_one({"_id": uid}, {"$set": {"ban": {"on": False, "reason": ""}}})


async def ban_status(uid):
    u = await get(uid)
    return (u or {}).get("ban", {"on": False, "reason": ""})


async def total():
    return await _c().count_documents({})


async def all_ids():
    return [u["_id"] async for u in _c().find({}, {"_id": 1})]


async def banned_count():
    return await _c().count_documents({"ban.on": True})


async def list_users(limit=50):
    return [u async for u in _c().find({}).limit(limit)]


# ---- premium ---------------------------------------------------------------
async def premium_until(uid):
    u = await get(uid)
    return (u or {}).get("premium_until")


async def is_premium(uid):
    until = await premium_until(uid)
    return bool(until and until > utcnow())


async def add_premium(uid, delta: timedelta):
    """Adds time on top of any remaining premium."""
    until = await premium_until(uid)
    base = until if until and until > utcnow() else utcnow()
    new = base + delta
    await _c().update_one({"_id": uid}, {"$set": {"premium_until": new}}, upsert=True)
    return new


async def remove_premium(uid):
    await _c().update_one({"_id": uid}, {"$unset": {"premium_until": ""}})


async def premium_left(uid):
    until = await premium_until(uid)
    if not until or until <= utcnow():
        return None
    return until - utcnow()


async def premium_count():
    return await _c().count_documents({"premium_until": {"$gt": utcnow()}})


async def use_trial(uid):
    """One-time trial flag. True if the trial was unused."""
    await _c().update_one({"_id": uid}, {"$setOnInsert": {"joined": utcnow(), "ban": {"on": False, "reason": ""}}}, upsert=True)
    r = await _c().update_one({"_id": uid, "trial_used": {"$ne": True}}, {"$set": {"trial_used": True}})
    return r.matched_count == 1
