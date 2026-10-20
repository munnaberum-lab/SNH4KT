"""Likes and playlists (accounts only)."""
from database import core, files
from utils import rand_b62, utcnow

MAX_PLAYLISTS, MAX_ITEMS = 50, 500


class Limit(Exception):
    pass


def _likes():
    return core.col("likes")


def _pl():
    return core.col("playlists")


async def like(uid, sid):
    """True when this call added the like."""
    r = await _likes().update_one({"uid": uid, "sid": sid}, {"$setOnInsert": {"uid": uid, "sid": sid, "at": utcnow()}}, upsert=True)
    if r.upserted_id is not None:
        d = await files.get_by_sid(sid)
        if d:
            await files.increment(d["_id"], "likes")
        return True
    return False


async def unlike(uid, sid):
    r = await _likes().delete_one({"uid": uid, "sid": sid})
    if r.deleted_count:
        d = await files.get_by_sid(sid)
        if d and d.get("likes", 0) > 0:
            await files.update(d["_id"], inc={"likes": -1})
        return True
    return False


async def liked_set(uid, sids):
    if not uid or not sids:
        return set()
    return {d["sid"] async for d in _likes().find({"uid": uid, "sid": {"$in": list(sids)}})}


async def list_likes(uid, page=1, limit=20):
    """Newest first. Returns (docs, has_more). Hidden or deleted videos are skipped."""
    rows = [d async for d in _likes().find({"uid": uid}).sort("at", -1)]
    start = (page - 1) * limit
    out = []
    for r in rows[start:start + limit]:
        v = await files.get_by_sid(r["sid"])
        if v and not v.get("hidden") and v.get("ok") is not False and v.get("bin"):
            out.append(v)
    return out, start + limit < len(rows)


# ---- playlists -------------------------------------------------------------
def clean_name(name):
    name = " ".join((name or "").split())[:60]
    if not name:
        raise ValueError("Give the playlist a name.")
    return name


async def create_playlist(uid, name):
    name = clean_name(name)
    if await _pl().count_documents({"uid": uid}) >= MAX_PLAYLISTS:
        raise Limit("You can have up to 50 playlists.")
    pid = rand_b62(10)
    await _pl().insert_one({"_id": pid, "uid": uid, "name": name, "items": [], "created": utcnow(), "updated": utcnow()})
    return pid


async def playlists(uid):
    return [p async for p in _pl().find({"uid": uid}).sort("created", -1)]


async def get_playlist(uid, pid):
    p = await _pl().find_one({"_id": pid, "uid": uid})
    return p


async def rename_playlist(uid, pid, name):
    r = await _pl().update_one({"_id": pid, "uid": uid}, {"$set": {"name": clean_name(name), "updated": utcnow()}})
    return r.matched_count == 1


async def delete_playlist(uid, pid):
    return (await _pl().delete_one({"_id": pid, "uid": uid})).deleted_count == 1


async def add_item(uid, pid, sid):
    p = await get_playlist(uid, pid)
    if not p:
        return None
    if sid in p["items"]:
        return False
    if len(p["items"]) >= MAX_ITEMS:
        raise Limit("A playlist can hold up to 500 videos.")
    await _pl().update_one({"_id": pid, "uid": uid}, {"$addToSet": {"items": sid}, "$set": {"updated": utcnow()}})
    return True


async def remove_item(uid, pid, sid):
    r = await _pl().update_one({"_id": pid, "uid": uid}, {"$pull": {"items": sid}})
    return r.matched_count == 1


async def playlist_videos(p):
    out = []
    for sid in p["items"]:
        v = await files.get_by_sid(sid)
        if v and not v.get("hidden") and v.get("ok") is not False and v.get("bin"):
            out.append(v)
    return out
