"""Persistent auto-delete queue."""
from datetime import timedelta

from database import core
from utils import utcnow


def _c():
    return core.col("autodelete")


async def add(chat, msg, seconds):
    await _c().insert_one({"chat": chat, "msg": msg, "at": utcnow() + timedelta(seconds=seconds)})


async def due(limit=200):
    return [d async for d in _c().find({"at": {"$lte": utcnow()}}).limit(limit)]


async def remove(doc_ids):
    if doc_ids:
        await _c().delete_many({"_id": {"$in": list(doc_ids)}})
