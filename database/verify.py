"""Verification tokens (persistent, TTL) and the verified-today marker."""
from datetime import timedelta

from database import core
from utils import rand_b62, today_str, utcnow

TOKEN_TTL = timedelta(hours=1)


async def create_token(uid, pending=None):
    """pending = short id of the file the user asked for (delivered right after verifying)."""
    token = rand_b62(16)
    await core.col("verify").insert_one({"uid": uid, "token": token, "used": False, "pending": pending,
                                         "expires": utcnow() + TOKEN_TTL})
    return token


async def consume_token(uid, token):
    """Returns {'pending': sid-or-None} once for the right user and an unused, unexpired token, else None."""
    flt = {"uid": uid, "token": token, "used": False, "expires": {"$gt": utcnow()}}
    doc = await core.col("verify").find_one(flt)
    if not doc:
        return None
    r = await core.col("verify").update_one(flt, {"$set": {"used": True}})
    if r.matched_count != 1:
        return None
    await mark_verified(uid)
    return {"pending": doc.get("pending")}


async def mark_verified(uid):
    end = utcnow() + timedelta(days=2)  # TTL cleans old rows; day string decides validity
    await core.col("verified").update_one({"_id": uid}, {"$set": {"day": today_str(), "expires": end}}, upsert=True)


async def is_verified_today(uid):
    d = await core.col("verified").find_one({"_id": uid})
    return bool(d and d.get("day") == today_str())
