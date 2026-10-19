"""Background enrichment of videos: one BIN copy, details, thumbnail, optional backup."""
import asyncio
import io
import logging

import info
import state
from database import files
from stream import thumbs
from utils import rand_b62

log = logging.getLogger("enrich")

_queue = None
_locks = {}
_queued = set()
progress = {"total": 0, "done": 0, "failed": 0}


def _q():
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def enqueue(_id):
    if _id in _queued:
        return False
    _queued.add(_id)
    progress["total"] += 1
    _q().put_nowait(_id)
    return True


async def enqueue_pending():
    n = 0
    for d in await files.videos_without_bin():
        n += enqueue(d["_id"])
    return n


def cancel_all():
    q = _q()
    dropped = 0
    while not q.empty():
        try:
            _queued.discard(q.get_nowait())
            dropped += 1
        except asyncio.QueueEmpty:
            break
    progress.update(total=progress["done"] + progress["failed"])
    return dropped


def _media_of(msg):
    return getattr(msg, "video", None) or getattr(msg, "document", None)


async def _flood_guard(coro_fn, *a, **k):
    """Run a Telegram call; on FloodWait sleep and retry once."""
    try:
        return await coro_fn(*a, **k)
    except Exception as e:  # noqa
        if type(e).__name__ == "FloodWait":
            await asyncio.sleep(int(getattr(e, "value", 5)) + 1)
            return await coro_fn(*a, **k)
        raise


async def ensure_bin(client, doc):
    """Copy the file to BIN_CHANNEL exactly once. Returns (doc, sent_message_or_None)."""
    lock = _locks.setdefault(doc["_id"], asyncio.Lock())
    async with lock:
        fresh = await files.get(doc["_id"]) or doc
        if fresh.get("bin"):
            return fresh, None
        sent = await _flood_guard(client.send_cached_media, info.BIN_CHANNEL, fresh["file_id"])
        won = await files.conditional_update({"_id": fresh["_id"], "bin": {"$exists": False}},
                                             {"bin": sent.id, "key": rand_b62(12), "ok": True})
        if not won:  # someone else created the copy first: remove ours
            try:
                await client.delete_messages(info.BIN_CHANNEL, sent.id)
            except Exception:  # noqa
                pass
            return await files.get(fresh["_id"]), None
        return await files.get(fresh["_id"]), sent
    _locks.pop(doc["_id"], None)


async def make_thumb(client, doc, media):
    """Telegram's own thumbnail, else a frame from ffmpeg. Returns JPEG bytes or None."""
    try:
        tl = getattr(media, "thumbs", None) or []
        if tl:
            bio = await _flood_guard(client.download_media, tl[0].file_id, in_memory=True)
            if bio:
                return bio.getvalue() if hasattr(bio, "getvalue") else bytes(bio)
    except Exception as e:  # noqa
        log.warning("telegram thumb failed: %s", e)
    url = f"http://127.0.0.1:{info.PORT}/stream/{doc['sid']}"
    return await thumbs.ffmpeg_thumb(url, thumbs.thumb_seek(doc.get("dur"), info.THUMB_AT_SECONDS))


async def store_thumb(client, doc, data):
    bio = io.BytesIO(data)
    bio.name = "thumb.jpg"
    sent = await _flood_guard(client.send_photo, info.BIN_CHANNEL, photo=bio)
    await files.update(doc["_id"], {"thumb": sent.id})
    thumbs.cache_put(doc["sid"], data)
    return sent.id


async def process(client, _id):
    doc = await files.get(_id)
    if not doc or doc.get("type") != "video":
        return False
    doc, sent = await ensure_bin(client, doc)
    upd = {}
    media = _media_of(sent) if sent is not None else None
    if media is None and (not doc.get("w") or not doc.get("h") or not doc.get("dur") or not doc.get("thumb")):
        try:
            m = await _flood_guard(client.get_messages, info.BIN_CHANNEL, doc["bin"])
            media = _media_of(m) if m and not getattr(m, "empty", False) else None
        except Exception as e:  # noqa
            log.warning("cannot read BIN message %s: %s", doc.get("bin"), e)
    if media is not None:
        w, h, dur = int(getattr(media, "width", 0) or 0), int(getattr(media, "height", 0) or 0), int(getattr(media, "duration", 0) or 0)
        if w and h:
            upd.update(w=w, h=h)
        if dur:
            upd["dur"] = dur
        if getattr(media, "mime_type", None):
            upd["mime"] = media.mime_type.lower()
    w, h = upd.get("w", doc.get("w")), upd.get("h", doc.get("h"))
    if not w or not h:  # ffprobe fallback (reads rotation tag)
        probe = await thumbs.ffprobe(f"http://127.0.0.1:{info.PORT}/stream/{doc['sid']}")
        if probe and probe["w"] and probe["h"]:
            upd.update(w=probe["w"], h=probe["h"])
            if probe["dur"]:
                upd["dur"] = probe["dur"]
    w, h = upd.get("w", doc.get("w")), upd.get("h", doc.get("h"))
    from ingest import compute_kind
    upd["kind"] = compute_kind(True, w, h, doc.get("kind_set"))
    doc.update(upd)
    await files.update(_id, upd)
    if not doc.get("thumb"):
        data = await make_thumb(client, doc, media)
        if data:
            await store_thumb(client, doc, data)
    if info.BACKUP_CHANNEL and not doc.get("backup"):
        try:
            await _flood_guard(client.send_cached_media, info.BACKUP_CHANNEL, doc["file_id"])
            await files.update(_id, {"backup": True})
        except Exception as e:  # noqa
            log.warning("backup copy failed: %s", e)
    return True


async def worker():
    """Single background worker, resumable (pending videos are re-queued at start)."""
    delay = 1.0 / max(info.ENRICH_RATE, 0.1)
    q = _q()
    while True:
        _id = await q.get()
        try:
            client = state.main
            ok = await process(client, _id)
            progress["done" if ok else "failed"] += 1
        except Exception as e:  # noqa
            progress["failed"] += 1
            log.warning("enrich %s failed: %s", _id, e)
        finally:
            _queued.discard(_id)
        await asyncio.sleep(delay)
