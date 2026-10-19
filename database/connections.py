"""Connect a group to a user's PM so settings and filters can be managed there."""
from database import core


def _c():
    return core.col("connections")


async def add(uid, group):
    d = await _c().find_one({"_id": uid})
    groups = (d or {}).get("groups", [])
    if group not in groups:
        groups.append(group)
    await _c().update_one({"_id": uid}, {"$set": {"groups": groups, "active": group}}, upsert=True)


async def active(uid):
    d = await _c().find_one({"_id": uid})
    return (d or {}).get("active")


async def groups(uid):
    d = await _c().find_one({"_id": uid})
    return (d or {}).get("groups", [])


async def set_active(uid, group):
    await _c().update_one({"_id": uid}, {"$set": {"active": group}})


async def remove(uid, group):
    d = await _c().find_one({"_id": uid})
    if not d:
        return
    gs = [g for g in d.get("groups", []) if g != group]
    await _c().update_one({"_id": uid}, {"$set": {"groups": gs, "active": gs[-1] if gs else None}})
