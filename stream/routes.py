"""aiohttp routes: /stream, /download, /thumb, legacy links."""
import logging
import mimetypes
from collections import defaultdict

from aiohttp import web

import access
import config
import info
import state
from database import files
from stream import clients, thumbs
from stream.ranges import RangeError, chunk_plan, content_disposition, parse_range
from stream.streamer import FileGone, streamer_for
from utils import TTLCache, valid_sid
from web import session

log = logging.getLogger("stream.routes")
_doc_cache = TTLCache(maxsize=500, ttl=60)
_ip_streams = defaultdict(int)


def _ip(request):
    fwd = request.headers.get("X-Forwarded-For")
    return (fwd.split(",")[0].strip() if fwd else request.remote) or "?"


def err(status, code, message, headers=None):
    return web.json_response({"error": {"code": code, "message": message}}, status=status, headers=headers)


async def get_doc(sid):
    if not valid_sid(sid):
        return None
    d = _doc_cache.get(sid)
    if d is None:
        d = await files.get_by_sid(sid)
        if d:
            _doc_cache.set(sid, d)
    if not d or d.get("hidden") or d.get("ok") is False or not d.get("bin"):
        return None
    return d


def forget(sid):
    _doc_cache.pop(sid)


async def serve_media(request, doc, attachment):
    if not info.STREAM_MODE:
        return err(503, "disabled", "Streaming is disabled")
    size = int(doc.get("size") or 0)
    try:
        start, end, partial = parse_range(request.headers.get("Range"), size)
    except RangeError:
        return web.Response(status=416, headers={"Content-Range": f"bytes */{size}"})
    cfg = await config.get()
    guarded = cfg["premium_mode"] or cfg["require_login"]
    if guarded:  # who is asking? a logged in browser, or an external player with a signed key
        uid = session.verify_stream_key(request.query.get("k", ""), doc["sid"]) if request.query.get("k") else None
        if uid is None:
            user = await session.load(request)
            uid = user["uid"] if user else None
        ok, reason = await access.check(uid, doc, "get" if attachment else "watch", consume=(attachment or start == 0), cfg=cfg)
        if not ok:
            status, code = {"login": (401, "login_required"), "premium": (403, "premium_only")}.get(reason, (403, "quota_reached"))
            return err(status, code, access.MESSAGES[reason])
    if clients.active_streams() >= info.MAX_STREAMS:
        return err(503, "busy", "Too many streams, retry shortly", {"Retry-After": "5"})
    ip = _ip(request)
    if _ip_streams[ip] >= info.PER_IP_STREAMS:
        return err(429, "too_many", "Too many streams from your address", {"Retry-After": "5"})
    name = doc.get("title") or doc.get("name") or "file"
    mime = doc.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {
        "Content-Type": mime, "Content-Length": str(end - start + 1), "Accept-Ranges": "bytes",
        "Cache-Control": ("private" if guarded else "public") + ", max-age=3600", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": content_disposition(name, attachment),
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    cid, client = clients.pick_client()
    streamer = streamer_for(cid, client)
    try:
        fid = await streamer.get_file_id(doc["bin"])
    except FileGone:
        await _mark_gone(doc)
        return err(404, "not_found", "Video unavailable")
    except Exception as e:  # noqa
        if type(e).__name__ == "FloodWait":
            return err(503, "busy", "Telegram is busy, retry shortly", {"Retry-After": "5"})
        log.warning("stream lookup failed: %s", e)
        return err(503, "unavailable", "Stream temporarily unavailable")
    if request.method == "HEAD":
        head = web.StreamResponse(status=206 if partial else 200, headers=headers)
        await head.prepare(request)
        return head
    if attachment and start == 0:
        await files.increment(doc["_id"], "dl")
    offset, first_cut, last_cut, parts = chunk_plan(start, end)
    resp = web.StreamResponse(status=206 if partial else 200, headers=headers)
    await resp.prepare(request)
    state.work_loads[cid] = state.work_loads.get(cid, 0) + 1
    _ip_streams[ip] += 1
    try:
        async for chunk in streamer.yield_file(fid, offset, first_cut, last_cut, parts):
            await resp.write(chunk)
        await resp.write_eof()
    except (ConnectionResetError, ConnectionError, web.HTTPException):
        pass  # client went away: stop immediately
    except Exception as e:  # noqa
        log.warning("stream error: %s", e)
    finally:
        state.work_loads[cid] = max(0, state.work_loads.get(cid, 1) - 1)
        _ip_streams[ip] = max(0, _ip_streams[ip] - 1)
        if _ip_streams[ip] == 0:
            _ip_streams.pop(ip, None)
    return resp


async def _mark_gone(doc):
    """BIN message is gone: try the backup channel, else mark the record unavailable."""
    forget(doc.get("sid", ""))
    if info.BACKUP_CHANNEL and state.main:
        try:
            sent = await state.main.send_cached_media(info.BIN_CHANNEL, doc["file_id"])
            await files.update(doc["_id"], {"bin": sent.id, "ok": True})
            return
        except Exception as e:  # noqa
            log.warning("backup recovery failed: %s", e)
    await files.update(doc["_id"], {"ok": False})


async def stream(request):
    doc = await get_doc(request.match_info["sid"])
    if not doc:
        return err(404, "not_found", "Video not found")
    return await serve_media(request, doc, attachment=False)


async def download(request):
    doc = await get_doc(request.match_info["sid"])
    if not doc:
        return err(404, "not_found", "Video not found")
    return await serve_media(request, doc, attachment=True)


_PLACEHOLDER = None


def _placeholder():
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static", "placeholder.jpg")
        try:
            with open(p, "rb") as f:
                _PLACEHOLDER = f.read()
        except OSError:
            _PLACEHOLDER = b""
    return _PLACEHOLDER


async def thumb(request):
    sid = request.match_info["sid"]
    headers = {"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}
    doc = await get_doc(sid)
    data = None
    if doc and doc.get("thumb"):
        data = thumbs.cache_get(sid)
        if data is None and state.main:
            try:
                bio = await state.main.download_media(await state.main.get_messages(info.BIN_CHANNEL, doc["thumb"]), in_memory=True)
                data = bio.getvalue() if bio else None
                if data:
                    thumbs.cache_put(sid, data)
            except Exception as e:  # noqa
                log.warning("thumb download failed: %s", e)
    if not data:
        headers["Cache-Control"] = "public, max-age=300"
        data = _placeholder()
    return web.Response(body=data, content_type="image/jpeg", headers=headers)


# ---- legacy links (LEGACY_LINKS=true) -------------------------------------
async def _legacy_doc(request):
    try:
        msg_id = int(request.match_info["msg"])
    except ValueError:
        return None
    d = await files.get_by_bin(msg_id)
    if not d or request.query.get("hash", "") != d["_id"][:6]:
        return None
    return d


async def legacy_raw(request):
    d = await _legacy_doc(request)
    if not d:
        return err(404, "not_found", "Video not found")
    return await serve_media(request, d, attachment=False)


async def legacy_watch(request):
    d = await _legacy_doc(request)
    if not d:
        return err(404, "not_found", "Video not found")
    path = "shorts" if d.get("kind") == "short" else "watch"
    raise web.HTTPFound(f"/{path}/{d['sid']}")


def add_routes(app):
    app.router.add_get("/stream/{sid}", stream)
    app.router.add_get("/download/{sid}", download)
    app.router.add_get("/thumb/{sid}.jpg", thumb)
    if info.LEGACY_LINKS:
        app.router.add_get(r"/watch/{msg:\d+}/{name}", legacy_watch)
        app.router.add_get(r"/{msg:\d+}/{name}", legacy_raw)
