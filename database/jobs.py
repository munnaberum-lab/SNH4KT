"""Index jobs (resumable)."""
from database import core
from utils import rand_b62, utcnow


def _c():
    return core.col("index_jobs")


async def create(chat, last_id, skip=0):
    jid = rand_b62(8)
    await _c().insert_one({"_id": jid, "chat": chat, "last_id": last_id, "skip": skip, "pos": skip, "done": 0,
                           "saved": 0, "dupes": 0, "errors": 0, "skipped": 0, "state": "running", "date": utcnow()})
    return jid


async def get(jid):
    return await _c().find_one({"_id": jid})


async def update(jid, fields=None, inc=None):
    ops = {}
    if fields:
        ops["$set"] = fields
    if inc:
        ops["$inc"] = inc
    await _c().update_one({"_id": jid}, ops)


async def running():
    return [j async for j in _c().find({"state": "running"})]
