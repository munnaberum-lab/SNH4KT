"""Referral counting. A joined user counts once for one owner."""
import info
from database import core, users
from utils import parse_duration


def _c():
    return core.col("referrals")


async def count(owner):
    return await _c().count_documents({"owner": owner})


async def add_referral(owner, joined_user):
    """Register a referral for a NEW user. Returns True when the reward triggered."""
    if owner == joined_user:
        return False
    try:
        r = await _c().update_one({"owner": owner, "joined_user": joined_user},
                                  {"$setOnInsert": {"owner": owner, "joined_user": joined_user}}, upsert=True)
    except Exception:
        return False
    if r.upserted_id is None:
        return False
    if info.REFERRAL_COUNT and await count(owner) >= info.REFERRAL_COUNT:
        deleted = await _c().delete_many({"owner": owner})
        if deleted.deleted_count >= info.REFERRAL_COUNT:  # the one caller that deleted them gets the reward
            delta = parse_duration(info.REFERRAL_PREMIUM_TIME)
            if delta:
                await users.add_premium(owner, delta)
                return True
    return False
