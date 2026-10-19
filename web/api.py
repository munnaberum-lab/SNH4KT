"""REST API v1 (JSON)."""
import json
import logging
import time

from aiohttp import web

import info
import state
from database import core, files, users
from stream import clients, thumbs
from stream.ranges import is_playable
from utils import TTLCache, utcnow, valid_sid
from web import auth

log = logging.getLogger("api")
_views = TTLCache(maxsize=50000, ttl=3600)
LIST_CACHE = {"Cache-Control": "public, max-age=30"}


def jerr(status, code, message, headers=None):
    return web.json_response({"error": {"code": code, "message": message}}, status=status, headers=headers)


def client_ip(request):
    fwd = request.headers.get("X-Forwarded-For")
    return (fwd.split(",")[0].strip() if fwd else request.remote) or "?"


def base_url(request):
    if info.URL:
        return info.URL
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    return f"{proto}://{request.host}"


def video_obj(d, base):
    sid, kind = d["sid"], d.get("kind")
    added = d.get("added")
    return {
        "id": sid, "title": d.get("title") or d.get("name"), "kind": kind,
        "w": d.get("w", 0), "h": d.get("h", 0), "dur": d.get("dur", 0), "size": d.get("size", 0),
        "quality": d.get("quality"), "lang": d.get("lang", []), "year": d.get("year"),
        "views": d.get("views", 0), "added": added.strftime("%Y-%m-%dT%H:%M:%SZ") if added else None,
        "playable": is_playable(d.get("mime"), d.get("size", 0)),
        "thumb": f"{base}/thumb/{sid}.jpg",
        "urls": {
            "page": f"{base}/{'shorts' if kind == 'short' else 'watch'}/{sid}",
            "stream": f"{base}/stream/{sid}", "download": f"{base}/download/{sid}",
            "telegram": f"https://t.me/{state.bot_username}?start=v_{sid}",
        },
    }


def _int(request, name, default, lo=1, hi=50):
    try:
        return max(lo, min(int(request.query.get(name, default)), hi))
    except ValueError:
        return default


async def _public_video(sid):
    if not valid_sid(sid):
        return None
    d = await files.get_by_sid(sid)
    if not d or d.get("hidden") or d.get("ok") is False or d.get("kind") not in ("short", "long") or not d.get("bin"):
        return None
    return d


# ---- public ---------------------------------------------------------------
async def list_videos(request):
    q = request.query
    kind = q.get("kind", "all")
    sort = q.get("sort", "new")
    if kind not in ("short", "long", "all") or sort not in ("new", "views", "random"):
        return jerr(400, "bad_request", "Invalid kind or sort")
    year = q.get("year")
    if year and not year.isdigit():
        return jerr(400, "bad_request", "Invalid year")
    items, total, more = await files.list_videos(
        kind=kind, sort=sort, q=q.get("q"), quality=q.get("quality"), lang=q.get("lang"), year=year,
        page=_int(request, "page", 1, 1, 100000), limit=_int(request, "limit", info.PAGE_SIZE))
    base = base_url(request)
    return web.json_response({"items": [video_obj(d, base) for d in items], "page": _int(request, "page", 1, 1, 100000),
                              "total": total, "has_more": more}, headers=LIST_CACHE)


async def get_video(request):
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    return web.json_response(video_obj(d, base_url(request)))


async def suggest_for(request):
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    limit = _int(request, "limit", info.SUGGEST_COUNT)
    skip = [x for x in request.query.get("exclude", "").split(",") if valid_sid(x)]
    skip_ids = []
    for s in skip:
        o = await files.get_by_sid(s)
        if o:
            skip_ids.append(o["_id"])
    items = await files.suggestions(d, limit=limit, skip_ids=skip_ids)
    base = base_url(request)
    return web.json_response({"items": [video_obj(x, base) for x in items]})


async def shorts_feed(request):
    after = request.query.get("after")
    if after and not valid_sid(after):
        return jerr(400, "bad_request", "Invalid cursor")
    limit = _int(request, "limit", info.SHORTS_BATCH)
    items, more = await files.shorts_after(after, limit)
    base = base_url(request)
    objs = [video_obj(d, base) for d in items]
    return web.json_response({"items": objs, "next": objs[-1]["id"] if objs and more else None}, headers=LIST_CACHE)


async def add_view(request):
    sid = request.match_info["id"]
    d = await _public_video(sid)
    if not d:
        return jerr(404, "not_found", "Video not found")
    key = (client_ip(request), sid)
    views = d.get("views", 0)
    if _views.get(key) is None:
        _views.set(key, True)
        await files.increment(d["_id"], "views")
        views += 1
    return web.json_response({"views": views})


async def search_suggest(request):
    q = (request.query.get("q") or "").strip()
    if len(q) < 2:
        return jerr(400, "bad_request", "q needs at least 2 characters")
    base = base_url(request)
    items = await files.suggest_search(q, 6)
    return web.json_response({"items": [{"id": d["sid"], "title": d.get("title") or d.get("name"), "kind": d.get("kind"),
                                         "thumb": f"{base}/thumb/{d['sid']}.jpg"} for d in items]})


async def health(request):
    ok_db = True
    try:
        await core.store.other.command("ping")
    except Exception:  # noqa
        ok_db = False
    return web.json_response({"ok": True, "db": ok_db, "clients": len(state.clients) or 1,
                              "uptime": int(time.time() - state.started_at)})


# ---- admin ----------------------------------------------------------------
def _need_admin(request):
    if not auth.enabled() or not auth.is_admin(request):
        return jerr(401, "unauthorized", "Login required")
    if request.method in ("POST", "PATCH", "DELETE", "PUT") and request.headers.get("X-Requested-With") != "fetch":
        return jerr(403, "forbidden", "Missing X-Requested-With header")
    return None


async def _json(request):
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa
        return {}


async def admin_login(request):
    if not auth.enabled():
        return jerr(403, "forbidden", "Admin is disabled")
    if request.headers.get("X-Requested-With") != "fetch":
        return jerr(403, "forbidden", "Missing X-Requested-With header")
    ip = client_ip(request)
    if not auth.login_limiter.allow(ip):
        return jerr(429, "rate_limited", "Too many tries. Wait 10 minutes.", {"Retry-After": "600"})
    data = await _json(request)
    if not auth.check_password(data.get("password", "")):
        return jerr(401, "unauthorized", "Wrong password")
    resp = web.json_response({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_cookie(), max_age=auth.MAX_AGE, httponly=True, secure=True, samesite="Strict", path="/")
    return resp


async def admin_logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie(auth.COOKIE, path="/")
    return resp


async def admin_stats(request):
    bad = _need_admin(request)
    if bad:
        return bad
    s = await files.stats()
    s.update(users=await users.total(), premium=await users.premium_count(), banned=await users.banned_count(),
             db_size_estimate=s["files"] * 1024, active_streams=clients.active_streams(),
             uptime=int(time.time() - state.started_at))
    return web.json_response(s)


async def admin_videos(request):
    bad = _need_admin(request)
    if bad:
        return bad
    q = request.query
    kind = q.get("kind", "all")
    items, total, more = await files.list_videos(kind=kind if kind in ("short", "long") else "all", q=q.get("q"),
                                                 page=_int(request, "page", 1, 1, 100000), limit=_int(request, "limit", 20),
                                                 include_hidden=True)
    if q.get("hidden") in ("1", "true"):
        items = [d for d in items if d.get("hidden")]
    base = base_url(request)
    out = []
    for d in items:
        o = video_obj(d, base)
        o.update(hidden=bool(d.get("hidden")), ok=d.get("ok", True), kind_set=d.get("kind_set"), name=d.get("name"))
        out.append(o)
    return web.json_response({"items": out, "total": total, "has_more": more})


async def admin_patch(request):
    bad = _need_admin(request)
    if bad:
        return bad
    d = await files.get_by_sid(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    data = await _json(request)
    fields, unset = {}, []
    if "title" in data:
        title = str(data["title"]).strip()[:300]
        if not title:
            return jerr(400, "bad_request", "Title cannot be empty")
        fields["title"] = title
    if "hidden" in data:
        fields["hidden"] = bool(data["hidden"])
    if "kind_set" in data:
        ks = data["kind_set"]
        if ks not in ("short", "long", None):
            return jerr(400, "bad_request", "kind_set must be short, long or null")
        from ingest import compute_kind
        if ks is None:
            unset.append("kind_set")
        else:
            fields["kind_set"] = ks
        fields["kind"] = compute_kind(d.get("type") == "video", d.get("w"), d.get("h"), ks)
    if not fields and not unset:
        return jerr(400, "bad_request", "Nothing to change")
    await files.update(d["_id"], fields, unset=unset)
    from stream import routes
    routes.forget(d["sid"])
    return web.json_response({"ok": True})


async def admin_thumb(request):
    bad = _need_admin(request)
    if bad:
        return bad
    d = await files.get_by_sid(request.match_info["id"])
    if not d or not d.get("bin"):
        return jerr(404, "not_found", "Video not found")
    data = None
    if (request.content_type or "").startswith("multipart/"):
        reader = await request.multipart()
        part = await reader.next()
        raw = await part.read(decode=False) if part else b""
        if raw[:3] != b"\xff\xd8\xff" and raw[:8] != b"\x89PNG\r\n\x1a\n":
            return jerr(400, "bad_request", "Upload a JPEG or PNG image")
        data = bytes(raw)[: 5 * 1024 * 1024]
    else:
        body = await _json(request)
        if not body.get("regenerate"):
            return jerr(400, "bad_request", "Send a file or {regenerate: true}")
        try:
            at = float(body.get("at", info.THUMB_AT_SECONDS))
        except (TypeError, ValueError):
            return jerr(400, "bad_request", "Invalid at")
        data = await thumbs.ffmpeg_thumb(f"http://127.0.0.1:{info.PORT}/stream/{d['sid']}", at)
        if not data:
            return jerr(503, "unavailable", "Could not create a thumbnail")
    import enrichment
    await enrichment.store_thumb(state.main, d, data)
    return web.json_response({"ok": True})


async def admin_delete(request):
    bad = _need_admin(request)
    if bad:
        return bad
    d = await files.get_by_sid(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    body = await _json(request)
    if body.get("stream_copy") and d.get("bin") and state.main:
        try:
            await state.main.delete_messages(info.BIN_CHANNEL, d["bin"])
        except Exception as e:  # noqa
            log.warning("could not delete BIN copy: %s", e)
    await files.delete_ids([d["_id"]])
    thumbs.cache_drop(d["sid"])
    from stream import routes
    routes.forget(d["sid"])
    return web.json_response({"ok": True})


def add_routes(app):
    r = app.router
    r.add_get("/api/v1/videos", list_videos)
    r.add_get("/api/v1/videos/{id}", get_video)
    r.add_get("/api/v1/videos/{id}/suggest", suggest_for)
    r.add_get("/api/v1/shorts", shorts_feed)
    r.add_post("/api/v1/videos/{id}/view", add_view)
    r.add_get("/api/v1/search/suggest", search_suggest)
    r.add_get("/health", health)
    r.add_post("/api/v1/admin/login", admin_login)
    r.add_post("/api/v1/admin/logout", admin_logout)
    r.add_get("/api/v1/admin/stats", admin_stats)
    r.add_get("/api/v1/admin/videos", admin_videos)
    r.add_patch("/api/v1/admin/videos/{id}", admin_patch)
    r.add_post("/api/v1/admin/videos/{id}/thumb", admin_thumb)
    r.add_delete("/api/v1/admin/videos/{id}", admin_delete)
