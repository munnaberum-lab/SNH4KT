"""The files collection: ingest storage, search, listing, counters."""
import re
from datetime import datetime

import info
from database import core
from utils import rand_b62, utcnow

PUBLIC = {"hidden": {"$ne": True}, "ok": {"$ne": False}, "kind": {"$in": ["short", "long"]}, "bin": {"$exists": True}}


def _size_error(e):
    msg = str(e).lower()
    return type(e).__name__ == "OperationFailure" and ("quota" in msg or "space" in msg or "too large" in msg or "size" in msg)


async def find_one(filter_):
    for c in core.files_cols():
        d = await c.find_one(filter_)
        if d:
            return d
    return None


async def get(_id):
    return await find_one({"_id": _id})


async def get_by_sid(sid):
    return await find_one({"sid": sid}) if sid else None


async def get_by_bin(msg_id):
    return await find_one({"bin": msg_id})


async def duplicate_exists(_id, name, size):
    for c in core.files_cols():
        if await c.find_one({"$or": [{"_id": _id}, {"name": name, "size": size}]}):
            return True
    return False


async def insert(doc):
    """Atomic insert. Returns 'saved' or 'duplicate'. Never makes two docs for one unique id."""
    if await duplicate_exists(doc["_id"], doc["name"], doc["size"]):
        return "duplicate"
    doc = dict(doc)
    doc.setdefault("sid", rand_b62(10))
    doc.setdefault("added", utcnow())
    last = None
    for c in core.files_cols():
        try:
            res = await c.update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        except Exception as e:  # noqa
            if _size_error(e):
                last = e
                continue
            if type(e).__name__ == "DuplicateKeyError":
                # sid collision (rare) or racing insert
                doc["sid"] = rand_b62(10)
                try:
                    res = await c.update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
                except Exception:
                    return "duplicate"
            else:
                raise
        return "saved" if res.upserted_id is not None else "duplicate"
    if last:
        raise last
    return "duplicate"


async def update(_id, fields=None, unset=None, inc=None):
    ops = {}
    if fields:
        ops["$set"] = fields
    if unset:
        ops["$unset"] = {k: "" for k in unset}
    if inc:
        ops["$inc"] = inc
    for c in core.files_cols():
        r = await c.update_one({"_id": _id}, ops)
        if r.matched_count:
            return True
    return False


async def conditional_update(filter_, fields):
    """Atomic set when filter matches. Returns True if a document was changed."""
    for c in core.files_cols():
        r = await c.update_one(filter_, {"$set": fields})
        if r.matched_count:
            return True
    return False


async def delete_ids(ids):
    n = 0
    for c in core.files_cols():
        r = await c.delete_many({"_id": {"$in": list(ids)}})
        n += r.deleted_count
    return n


async def delete_all():
    n = 0
    for c in core.files_cols():
        r = await c.delete_many({})
        n += r.deleted_count
    return n


def _regex_all(words):
    return [re.compile("^" + re.escape(w)) for w in words]


def build_query(text, quality=None, lang=None, year=None, season=None, episode=None, caption_filter=False):
    q = {}
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    if words:
        q["tokens"] = {"$all": _regex_all(words)}
    if quality:
        q["quality"] = quality
    if lang:
        q["lang"] = lang
    if year:
        q["year"] = int(year)
    if season:
        q["season"] = int(season)
    if episode:
        q["episode"] = int(episode)
    return q


async def search(text, offset=0, limit=10, **filters):
    """Anchored-prefix token search across all file databases. Returns (files, next_offset, total)."""
    q = build_query(text, **filters)
    if not q:
        return [], "", 0
    total, docs = 0, []
    for c in core.files_cols():
        total += await c.count_documents(q)
        cur = c.find(q).sort("added", -1).limit(offset + limit)
        async for d in cur:
            docs.append(d)
    docs.sort(key=lambda d: d.get("added") or datetime.min, reverse=True)
    seen, merged = set(), []
    for d in docs:
        if d["_id"] not in seen:
            seen.add(d["_id"])
            merged.append(d)
    page = merged[offset:offset + limit]
    nxt = offset + limit if offset + limit < total else ""
    return page, nxt, total


async def count_keyword(keyword):
    q = build_query(keyword)
    return sum([await c.count_documents(q) for c in core.files_cols()]) if q else 0


async def delete_keyword(keyword):
    q = build_query(keyword)
    n = 0
    if not q:
        return 0
    for c in core.files_cols():
        n += (await c.delete_many(q)).deleted_count
    return n


async def total_count(extra=None):
    return sum([await c.count_documents(extra or {}) for c in core.files_cols()])


# ---- website listing -------------------------------------------------------
def _public(extra=None):
    q = dict(PUBLIC)
    if extra:
        q.update(extra)
    return q


async def list_videos(kind="all", sort="new", q=None, quality=None, lang=None, year=None,
                      page=1, limit=12, include_hidden=False):
    base = {}
    if include_hidden:
        base["kind"] = {"$in": ["short", "long"]} if kind == "all" else kind
    else:
        base = _public()
        if kind in ("short", "long"):
            base["kind"] = kind
    if q:
        words = re.findall(r"[a-z0-9]+", q.lower())
        if words:
            base["tokens"] = {"$all": _regex_all(words)}
    if quality:
        base["quality"] = quality
    if lang:
        base["lang"] = lang.lower()
    if year:
        base["year"] = int(year)
    limit = max(1, min(int(limit), 50))
    page = max(1, int(page))
    skip = (page - 1) * limit
    total, docs = 0, []
    for c in core.files_cols():
        total += await c.count_documents(base)
        if sort == "random":
            cur = c.aggregate([{"$match": base}, {"$sample": {"size": limit}}])
        else:
            key = "views" if sort == "views" else "added"
            cur = c.find(base).sort(key, -1).limit(skip + limit)
        async for d in cur:
            docs.append(d)
    if sort == "views":
        docs.sort(key=lambda d: d.get("views", 0), reverse=True)
    elif sort != "random":
        docs.sort(key=lambda d: d.get("added") or datetime.min, reverse=True)
    items = docs[:limit] if sort == "random" else docs[skip:skip + limit]
    return items, total, skip + len(items) < total


async def shorts_after(after_sid=None, limit=10):
    """Keyset pagination, newest first."""
    q = _public({"kind": "short"})
    if after_sid:
        ref = await get_by_sid(after_sid)
        if ref:
            q["$or"] = [{"added": {"$lt": ref["added"]}}, {"added": ref["added"], "_id": {"$lt": ref["_id"]}}]
    docs = []
    for c in core.files_cols():
        async for d in c.find(q).sort("added", -1).limit(limit + 1):
            docs.append(d)
    docs.sort(key=lambda d: (d.get("added") or datetime.min, d["_id"]), reverse=True)
    more = len(docs) > limit
    return docs[:limit], more


async def suggestions(doc, limit=12, skip_ids=()):
    """Mix: same kind with shared title words (~5), newest (~4), random older (~3). Never empty if others exist."""
    limit = max(1, limit)
    n_rel, n_new = round(limit * 5 / 12), round(limit * 4 / 12)
    chosen, ids = [], {doc["_id"], *skip_ids}

    def take(items, n):
        for d in items:
            if len(chosen) >= limit or n <= 0:
                return
            if d["_id"] not in ids:
                ids.add(d["_id"])
                chosen.append(d)
                n -= 1

    words = [w for w in (doc.get("tokens") or []) if len(w) > 2][:6]
    if words:
        rel, _, _ = await list_videos(kind=doc.get("kind", "all"), q=None, limit=50)
        scored = [d for d in rel if set(words) & set(d.get("tokens") or [])]
        take(scored, n_rel)
    new, _, _ = await list_videos(kind="all", sort="new", limit=limit + 4)
    take(new, n_new)
    rnd, _, _ = await list_videos(kind="all", sort="random", limit=limit)
    take(rnd, limit - len(chosen))
    if len(chosen) < limit:
        allv, _, _ = await list_videos(kind="all", sort="new", limit=50)
        take(allv, limit - len(chosen))
    return chosen


async def suggest_search(q, limit=6):
    items, _, _ = await list_videos(kind="all", q=q, limit=limit)
    return items


async def increment(_id, field):
    await update(_id, inc={field: 1})


async def stats():
    pub = _public()
    out = {"files": await total_count(), "videos": await total_count({"kind": {"$in": ["short", "long"]}}),
           "shorts": await total_count({"kind": "short"}), "longs": await total_count({"kind": "long"}),
           "hidden": await total_count({"hidden": True}), "views": 0}
    for c in core.files_cols():
        async for d in c.find({}, {"views": 1}):
            out["views"] += d.get("views", 0)
    out["public"] = await total_count(pub)
    return out


async def videos_without_bin():
    out = []
    for c in core.files_cols():
        async for d in c.find({"type": {"$in": ["video", "document"]}, "bin": {"$exists": False}, "ok": {"$ne": False}}):
            if d.get("type") == "video" or (d.get("mime") or "").startswith("video"):
                out.append(d)
    return out
