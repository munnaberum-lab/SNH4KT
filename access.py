"""Who may watch or get which video (website and bot use the same rules)."""
from datetime import timedelta

import config
import info
from database import core, users
from utils import today_str, utcnow

MESSAGES = {
    "login": "Login or create an account to continue.",
    "premium": "This video is for premium members only.",
    "quota": "You used today's free limit. Come back tomorrow or get premium.",
}


async def is_premium(uid):
    return bool(uid) and (uid in info.ADMINS or await users.is_premium(uid))


async def check(uid, doc, action="watch", consume=False, cfg=None):
    """-> (allowed, reason). action: 'watch' (website player) or 'get' (download or bot delivery).
    reason is login, premium or quota. With premium mode off everything is free (login only if required)."""
    c = cfg or await config.get()
    if not uid:
        return (False, "login") if (c["require_login"] or c["premium_mode"]) else (True, None)
    if not c["premium_mode"] or await is_premium(uid):
        return True, None
    if doc.get("premium"):
        return False, "premium"
    limit = c["free_watch_per_day"] if action == "watch" else c["free_get_per_day"]
    if limit <= 0:
        return True, None
    qid = f"{uid}:{today_str()}"
    row = await core.col("quota").find_one({"_id": qid}) or {}
    used = row.get(action, [])
    if doc["sid"] in used:
        return True, None
    if len(used) >= limit:
        return False, "quota"
    if consume:
        await core.col("quota").update_one({"_id": qid}, {"$addToSet": {action: doc["sid"]}, "$setOnInsert": {"uid": uid, "expires": utcnow() + timedelta(days=2)}}, upsert=True)
    return True, None


def lock_flag(doc, cfg, premium_user):
    """Cheap flag for lists (no database): True when this video is premium-only for this viewer."""
    return bool(cfg["premium_mode"] and doc.get("premium") and not premium_user)
