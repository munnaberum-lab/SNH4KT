"""REST API v1 (JSON): public, account (likes, playlists), admin."""
import logging
import time

from aiohttp import web

import access
import config
import info
import state
from database import accounts, core, files, social, users
from stream import clients, thumbs
from stream.ranges import is_playable
from utils import TTLCache, utcnow, valid_sid
from web import auth, session
from web.ratelimit import RateLimiter

log = logging.getLogger("api")
_views = TTLCache(maxsize=50000, ttl=3600)
user_login_limiter = RateLimiter(10, 600)    # per IP
user_aid_limiter = RateLimiter(8, 900)       # per account ID
LIST_CACHE = {"Cache-Control": "public, max-age=30"}
PRIVATE = {"Cache-Control": "private, no-store"}


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


def video_obj(d, base, liked=False, locked=False, premium_mode=False):
    sid, kind = d["sid"], d.get("kind")
    added = d.get("added")
    return {
        "id": sid, "title": d.get("title") or d.get("name"), "kind": kind,
        "w": d.get("w", 0), "h": d.get("h", 0), "dur": d.get("dur", 0), "size": d.get("size", 0),
        "quality": d.get("quality"), "lang": d.get("lang", []), "year": d.get("year"), "tags": d.get("tags", []),
        "views": d.get("views", 0), "likes": d.get("likes", 0), "liked": bool(liked),
        "premium": bool(d.get("premium")) and premium_mode, "locked": bool(locked),
        "added": added.strftime("%Y-%m-%dT%H:%M:%SZ") if added else None,
        "playable": is_playable(d.get("mime"), d.get("size", 0)),
        "thumb": f"{base}/thumb/{sid}.jpg",
        "urls": {
            "page": f"{base}/{'shorts' if kind == 'short' else 'watch'}/{sid}",
            "stream": f"{base}/stream/{sid}", "download": f"{base}/download/{sid}",
            "telegram": f"https://t.me/{state.bot_username}?start=v_{sid}",
        },
    }


async def decorate(docs, base, user):
    """Video objects with this viewer's like and lock state."""
    c = await config.get()
    liked = await social.liked_set(user["uid"], [d["sid"] for d in docs]) if user else set()
    prem = await access.is_premium(user["uid"]) if user else False
    return [video_obj(d, base, d["sid"] in liked, access.lock_flag(d, c, prem), c["premium_mode"]) for d in docs]


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


async def _json(request):
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa
        return {}


def _csrf(request):
    if request.method in ("POST", "PATCH", "DELETE", "PUT") and request.headers.get("X-Requested-With") != "fetch":
        return jerr(403, "forbidden", "Missing X-Requested-With header")
    return None


async def _need_user(request):
    """-> (user, None) or (None, error response)."""
    bad = _csrf(request)
    if bad:
        return None, bad
    user = await session.load(request)
    if not user:
        return None, jerr(401, "login_required", "Login to use this.")
    return user, None


# ---- public videos -------------------------------------------------------------
async def list_videos(request):
    q = request.query
    kind = q.get("kind", "all")
    sort = q.get("sort", "new")
    if kind not in ("short", "long", "all") or sort not in ("new", "views", "random", "relevance"):
        return jerr(400, "bad_request", "Invalid kind or sort")
    year = q.get("year")
    if year and not year.isdigit():
        return jerr(400, "bad_request", "Invalid year")
    page, limit = _int(request, "page", 1, 1, 100000), _int(request, "limit", info.PAGE_SIZE)
    args = dict(kind=kind, sort=sort, quality=q.get("quality"), lang=q.get("lang"), year=year, tag=q.get("tag"), page=page, limit=limit)
    items, total, more = await files.list_videos(q=q.get("q"), **args)
    corrected = None
    if q.get("q") and total == 0:
        corrected = await files.fuzzy(q["q"])
        if corrected:
            items, total, more = await files.list_videos(q=corrected, **args)
    user = await session.load(request)
    body = {"items": await decorate(items, base_url(request), user), "page": page, "total": total, "has_more": more}
    if corrected:
        body["corrected"] = corrected
    return web.json_response(body, headers=PRIVATE if user else LIST_CACHE)


async def get_video(request):
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    user = await session.load(request)
    return web.json_response((await decorate([d], base_url(request), user))[0], headers=PRIVATE)


async def video_access(request):
    """Can this viewer watch it? Does not use up any daily limit."""
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    user = await session.load(request)
    ok, reason = await access.check(user["uid"] if user else None, d, "watch")
    return web.json_response({"ok": ok, "reason": reason, "message": access.MESSAGES.get(reason, "")}, headers=PRIVATE)


async def video_play(request):
    """Playable URL for the mobile app (adds a signed stream key for logged-in users)."""
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    user = await session.load(request)
    ok, reason = await access.check(user["uid"] if user else None, d, "watch")
    if not ok:
        return jerr(403, reason or "forbidden", access.MESSAGES.get(reason, "Not allowed"))
    url = f"{base_url(request)}/stream/{d['sid']}"
    if user:
        url += "?k=" + session.stream_key(user["uid"], d["sid"])
    return web.json_response({"url": url}, headers=PRIVATE)


async def suggest_for(request):
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    limit = _int(request, "limit", info.SUGGEST_COUNT)
    skip_ids = []
    for s in [x for x in request.query.get("exclude", "").split(",") if valid_sid(x)]:
        o = await files.get_by_sid(s)
        if o:
            skip_ids.append(o["_id"])
    items = await files.suggestions(d, limit=limit, skip_ids=skip_ids)
    user = await session.load(request)
    return web.json_response({"items": await decorate(items, base_url(request), user)}, headers=PRIVATE if user else {})


async def shorts_feed(request):
    after = request.query.get("after")
    if after and not valid_sid(after):
        return jerr(400, "bad_request", "Invalid cursor")
    items, more = await files.shorts_after(after, _int(request, "limit", info.SHORTS_BATCH))
    user = await session.load(request)
    objs = await decorate(items, base_url(request), user)
    return web.json_response({"items": objs, "next": objs[-1]["id"] if objs and more else None}, headers=PRIVATE if user else LIST_CACHE)


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


async def tags_list(request):
    return web.json_response({"tags": await files.popular_tags(30)}, headers=LIST_CACHE)


async def health(request):
    ok_db = True
    try:
        await core.store.other.command("ping")
    except Exception:  # noqa
        ok_db = False
    return web.json_response({"ok": True, "db": ok_db, "clients": len(state.clients) or 1, "uptime": int(time.time() - state.started_at)})


# ---- account: login, me, password ---------------------------------------------
async def me(request):
    c = await config.get()
    user = await session.load(request)
    out = {"logged_in": bool(user), "premium_mode": c["premium_mode"], "require_login": c["require_login"], "bot": state.bot_username}
    if user:
        left = await users.premium_left(user["uid"])
        out.update(aid=user["aid"], premium=bool(left) or user["uid"] in info.ADMINS, premium_days=left.days if left else 0)
    return web.json_response(out, headers=PRIVATE)


async def login(request):
    bad = _csrf(request)
    if bad:
        return bad
    data = await _json(request)
    aid = str(data.get("id", "")).strip().lower()[:30]
    ip = client_ip(request)
    if not user_login_limiter.allow(ip) or not user_aid_limiter.allow(aid):
        return jerr(429, "rate_limited", "Too many tries. Wait a few minutes.", {"Retry-After": "600"})
    acc = await accounts.verify(aid, str(data.get("password", ""))[:100])
    if not acc:
        return jerr(401, "bad_login", "Wrong ID or password.")
    user_aid_limiter.reset(aid)
    resp = web.json_response({"ok": True, "aid": acc["aid"], "token": await session.make_token(acc["_id"])}, headers=PRIVATE)
    await session.set_cookie(resp, acc["_id"])
    return resp


async def logout(request):
    resp = web.json_response({"ok": True})
    session.clear_cookie(resp)
    return resp


async def change_password(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    data = await _json(request)
    if not user_aid_limiter.allow("pw:" + user["aid"]):
        return jerr(429, "rate_limited", "Too many tries. Wait a few minutes.")
    if not await accounts.verify(user["aid"], str(data.get("current", ""))[:100]):
        return jerr(401, "bad_login", "Current password is wrong.")
    try:
        await accounts.set_password(user["uid"], str(data.get("new", "")))
    except ValueError as e:
        return jerr(400, "bad_request", str(e))
    resp = web.json_response({"ok": True})
    await session.set_cookie(resp, user["uid"])  # this browser stays logged in, others are logged out
    return resp


# ---- likes and playlists ----------------------------------------------------------
async def like_video(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    d = await _public_video(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    want = bool((await _json(request)).get("like", True))
    changed = await (social.like(user["uid"], d["sid"]) if want else social.unlike(user["uid"], d["sid"]))
    fresh = await files.get(d["_id"])
    return web.json_response({"liked": want, "likes": fresh.get("likes", 0), "changed": changed})


async def my_likes(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    items, more = await social.list_likes(user["uid"], _int(request, "page", 1, 1, 10000), 20)
    return web.json_response({"items": await decorate(items, base_url(request), user), "has_more": more}, headers=PRIVATE)


async def my_playlists(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    vid = request.query.get("video", "")
    rows = await social.playlists(user["uid"])
    return web.json_response({"items": [{"id": p["_id"], "name": p["name"], "count": len(p["items"]), "has": vid in p["items"]} for p in rows]}, headers=PRIVATE)


async def create_playlist(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    data = await _json(request)
    try:
        pid = await social.create_playlist(user["uid"], str(data.get("name", "")))
        vid = data.get("video")
        if vid and valid_sid(vid) and await _public_video(vid):
            await social.add_item(user["uid"], pid, vid)
    except (ValueError, social.Limit) as e:
        return jerr(400, "bad_request", str(e))
    return web.json_response({"id": pid}, status=201)


async def get_playlist(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    p = await social.get_playlist(user["uid"], request.match_info["pid"])
    if not p:
        return jerr(404, "not_found", "Playlist not found")
    vids = await social.playlist_videos(p)
    return web.json_response({"id": p["_id"], "name": p["name"], "items": await decorate(vids, base_url(request), user)}, headers=PRIVATE)


async def edit_playlist(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    try:
        ok = await social.rename_playlist(user["uid"], request.match_info["pid"], str((await _json(request)).get("name", "")))
    except ValueError as e:
        return jerr(400, "bad_request", str(e))
    return web.json_response({"ok": ok}) if ok else jerr(404, "not_found", "Playlist not found")


async def remove_playlist(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    ok = await social.delete_playlist(user["uid"], request.match_info["pid"])
    return web.json_response({"ok": True}) if ok else jerr(404, "not_found", "Playlist not found")


async def playlist_add(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    sid = str((await _json(request)).get("video", ""))
    if not valid_sid(sid) or not await _public_video(sid):
        return jerr(404, "not_found", "Video not found")
    try:
        res = await social.add_item(user["uid"], request.match_info["pid"], sid)
    except social.Limit as e:
        return jerr(400, "bad_request", str(e))
    if res is None:
        return jerr(404, "not_found", "Playlist not found")
    return web.json_response({"ok": True, "added": res})


async def playlist_remove(request):
    user, bad = await _need_user(request)
    if bad:
        return bad
    ok = await social.remove_item(user["uid"], request.match_info["pid"], request.match_info["sid"])
    return web.json_response({"ok": True}) if ok else jerr(404, "not_found", "Playlist not found")


# ---- admin ---------------------------------------------------------------------------
def _admin(request):
    """-> (admin uid, None) or (None, error response)."""
    uid = auth.admin_uid(request)
    if not uid:
        return None, jerr(401, "unauthorized", "Admin login required")
    bad = _csrf(request)
    return (None, bad) if bad else (uid, None)


async def admin_start(request):
    bad = _csrf(request)
    if bad:
        return bad
    ip = client_ip(request)
    data = await _json(request)
    aid = str(data.get("id", "")).strip().lower()[:30]
    if not auth.login_limiter.allow(ip) or not auth.aid_limiter.allow(aid):
        return jerr(429, "rate_limited", "Too many tries. Wait 10 minutes.", {"Retry-After": "600"})
    cid = await auth.start_login(aid, str(data.get("password", ""))[:100])
    if not cid:
        return jerr(401, "unauthorized", "Wrong ID or password, or this account is not an owner.")
    return web.json_response({"challenge": cid, "message": "A code was sent to your Telegram."})


async def admin_verify(request):
    bad = _csrf(request)
    if bad:
        return bad
    ip = client_ip(request)
    if not auth.otp_limiter.allow(ip):
        return jerr(429, "rate_limited", "Too many tries. Wait 10 minutes.", {"Retry-After": "600"})
    data = await _json(request)
    uid = await auth.verify_code(str(data.get("challenge", ""))[:40], str(data.get("code", ""))[:10])
    if not uid:
        return jerr(401, "unauthorized", "Wrong or expired code.")
    await auth.audit(uid, "login", "", ip)
    try:
        if state.main:
            await state.main.send_message(info.LOG_CHANNEL, f"🔐 Admin panel login by <code>{uid}</code> from <code>{ip}</code>")
    except Exception:  # noqa
        pass
    resp = web.json_response({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_cookie(uid, request), max_age=info.ADMIN_SESSION_MINUTES * 60, httponly=True, secure=True, samesite="Strict", path="/")
    return resp


async def admin_logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie(auth.COOKIE, path="/")
    return resp


async def admin_stats(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    s = await files.stats()
    s.update(users=await users.total(), premium=await users.premium_count(), banned=await users.banned_count(),
             accounts=await core.col("accounts").count_documents({}), premium_videos=await files.total_count({"premium": True}),
             active_streams=clients.active_streams(), uptime=int(time.time() - state.started_at))
    return web.json_response(s, headers=PRIVATE)


async def admin_config_get(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    return web.json_response({"config": await config.get(fresh=True)}, headers=PRIVATE)


async def admin_config_put(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    data = await _json(request)
    try:
        new = await config.update({k: v for k, v in data.items() if k in config.SCHEMA})
    except ValueError as e:
        return jerr(400, "bad_request", str(e))
    await auth.audit(uid, "config", data, client_ip(request))
    return web.json_response({"config": new})


def _admin_video(d, base):
    o = video_obj(d, base, premium_mode=True)
    o.update(hidden=bool(d.get("hidden")), ok=d.get("ok", True), kind_set=d.get("kind_set"), name=d.get("name"), premium=bool(d.get("premium")))
    return o


async def admin_videos(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    q = request.query
    kind = q.get("kind", "all")
    items, total, more = await files.list_videos(kind=kind if kind in ("short", "long") else "all", q=q.get("q"), tag=q.get("tag"),
                                                 page=_int(request, "page", 1, 1, 100000), limit=_int(request, "limit", 20), include_hidden=True)
    if q.get("hidden") in ("1", "true"):
        items = [d for d in items if d.get("hidden")]
    if q.get("premium") in ("1", "true"):
        items = [d for d in items if d.get("premium")]
    base = base_url(request)
    return web.json_response({"items": [_admin_video(d, base) for d in items], "total": total, "has_more": more}, headers=PRIVATE)


async def _apply_video_changes(d, data):
    """Validated field changes for one video. Returns (fields, unset) or raises ValueError."""
    fields, unset = {}, []
    title, tags = d.get("title") or d.get("name"), d.get("tags", [])
    if "title" in data:
        title = " ".join(str(data["title"]).split())[:300]
        if not title:
            raise ValueError("Title cannot be empty")
        fields["title"] = title
    if "tags" in data:
        raw = data["tags"].split(",") if isinstance(data["tags"], str) else data["tags"]
        if not isinstance(raw, list):
            raise ValueError("tags must be a list or comma separated text")
        tags = files.clean_tags(raw)
        fields["tags"] = tags
    if "title" in fields or "tags" in fields:
        fields["tokens"] = files.retoken(d, title, tags)
    if "hidden" in data:
        fields["hidden"] = bool(data["hidden"])
    if "premium" in data:
        fields["premium"] = bool(data["premium"])
    if "kind_set" in data:
        ks = data["kind_set"]
        if ks not in ("short", "long", None):
            raise ValueError("kind_set must be short, long or null")
        from ingest import compute_kind
        if ks is None:
            unset.append("kind_set")
        else:
            fields["kind_set"] = ks
        fields["kind"] = compute_kind(d.get("type") == "video", d.get("w"), d.get("h"), ks)
    if not fields and not unset:
        raise ValueError("Nothing to change")
    return fields, unset


async def admin_patch(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    d = await files.get_by_sid(request.match_info["id"])
    if not d:
        return jerr(404, "not_found", "Video not found")
    data = await _json(request)
    try:
        fields, unset = await _apply_video_changes(d, data)
    except ValueError as e:
        return jerr(400, "bad_request", str(e))
    await files.update(d["_id"], fields, unset=unset)
    files.reset_caches()
    from stream import routes
    routes.forget(d["sid"])
    await auth.audit(uid, "video.edit", f"{d['sid']} {sorted(data)}", client_ip(request))
    return web.json_response({"ok": True})


async def admin_bulk(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    data = await _json(request)
    ids = [x for x in data.get("ids", []) if valid_sid(x)][:100]
    action, value = data.get("action"), data.get("value")
    if not ids or action not in ("premium", "hidden", "add_tag", "remove_tag"):
        return jerr(400, "bad_request", "Pick videos and an action")
    n = 0
    for sid in ids:
        d = await files.get_by_sid(sid)
        if not d:
            continue
        if action in ("premium", "hidden"):
            await files.update(d["_id"], {action: bool(value)})
        else:
            tags = list(d.get("tags", []))
            clean = files.clean_tags([value])
            if not clean:
                return jerr(400, "bad_request", "Invalid tag")
            tags = files.clean_tags(tags + clean) if action == "add_tag" else [t for t in tags if t != clean[0]]
            await files.update(d["_id"], {"tags": tags, "tokens": files.retoken(d, None, tags)})
        n += 1
    files.reset_caches()
    from stream import routes
    routes._doc_cache._d.clear()
    await auth.audit(uid, f"bulk.{action}", f"{n} videos value={value}", client_ip(request))
    return web.json_response({"ok": True, "changed": n})


async def admin_thumb(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    d = await files.get_by_sid(request.match_info["id"])
    if not d or not d.get("bin"):
        return jerr(404, "not_found", "Video not found")
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
    await auth.audit(uid, "video.thumb", d["sid"], client_ip(request))
    return web.json_response({"ok": True})


async def admin_delete(request):
    uid, bad = _admin(request)
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
    await auth.audit(uid, "video.delete", d["sid"], client_ip(request))
    return web.json_response({"ok": True})


async def admin_users(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    q = (request.query.get("q") or "").strip().lower()
    if not q:
        return web.json_response({"items": []})
    acc = await accounts.get(int(q)) if q.isdigit() else await accounts.get_by_aid(q)
    tg = int(q) if q.isdigit() else (acc["_id"] if acc else None)
    u = await users.get(tg) if tg else None
    if not u and not acc:
        return web.json_response({"items": []})
    left = await users.premium_left(tg)
    return web.json_response({"items": [{"uid": tg, "aid": acc["aid"] if acc else None, "name": (u or {}).get("name", ""),
                                         "premium_days": left.days if left else 0, "banned": bool((u or {}).get("ban", {}).get("on")),
                                         "joined": ((u or {}).get("joined") or utcnow()).strftime("%Y-%m-%d")}]})


async def admin_user_premium(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    try:
        tg = int(request.match_info["uid"])
    except ValueError:
        return jerr(400, "bad_request", "Invalid user")
    from datetime import timedelta
    data = await _json(request)
    if request.method == "DELETE":
        await users.remove_premium(tg)
        action = "premium.remove"
    else:
        try:
            days = int(data.get("days", 0))
        except (TypeError, ValueError):
            days = 0
        if not 1 <= days <= 3650:
            return jerr(400, "bad_request", "days must be 1 to 3650")
        await users.add_premium(tg, timedelta(days=days))
        action = f"premium.add {days}d"
    await auth.audit(uid, action, tg, client_ip(request))
    return web.json_response({"ok": True})


async def admin_user_ban(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    try:
        tg = int(request.match_info["uid"])
    except ValueError:
        return jerr(400, "bad_request", "Invalid user")
    data = await _json(request)
    if tg in info.ADMINS:
        return jerr(400, "bad_request", "Owners cannot be banned")
    if data.get("ban", True):
        await users.ban(tg, str(data.get("reason", "No reason"))[:100])
    else:
        await users.unban(tg)
    await auth.audit(uid, "ban" if data.get("ban", True) else "unban", tg, client_ip(request))
    return web.json_response({"ok": True})


async def admin_audit(request):
    uid, bad = _admin(request)
    if bad:
        return bad
    rows = [r async for r in core.col("audit").find({}).sort("at", -1).limit(60)]
    return web.json_response({"items": [{"uid": r["uid"], "action": r["action"], "detail": r.get("detail", ""), "ip": r.get("ip", ""),
                                         "at": r["at"].strftime("%Y-%m-%d %H:%M:%S")} for r in rows]}, headers=PRIVATE)


def add_routes(app):
    r = app.router
    r.add_get("/api/v1/videos", list_videos)
    r.add_get("/api/v1/videos/{id}", get_video)
    r.add_get("/api/v1/videos/{id}/access", video_access)
    r.add_get("/api/v1/videos/{id}/play", video_play)
    r.add_get("/api/v1/videos/{id}/suggest", suggest_for)
    r.add_get("/api/v1/shorts", shorts_feed)
    r.add_post("/api/v1/videos/{id}/view", add_view)
    r.add_post("/api/v1/videos/{id}/like", like_video)
    r.add_get("/api/v1/search/suggest", search_suggest)
    r.add_get("/api/v1/tags", tags_list)
    r.add_get("/health", health)
    r.add_get("/api/v1/me", me)
    r.add_post("/api/v1/auth/login", login)
    r.add_post("/api/v1/auth/logout", logout)
    r.add_post("/api/v1/me/password", change_password)
    r.add_get("/api/v1/me/likes", my_likes)
    r.add_get("/api/v1/me/playlists", my_playlists)
    r.add_post("/api/v1/me/playlists", create_playlist)
    r.add_get("/api/v1/me/playlists/{pid}", get_playlist)
    r.add_patch("/api/v1/me/playlists/{pid}", edit_playlist)
    r.add_delete("/api/v1/me/playlists/{pid}", remove_playlist)
    r.add_post("/api/v1/me/playlists/{pid}/items", playlist_add)
    r.add_delete("/api/v1/me/playlists/{pid}/items/{sid}", playlist_remove)
    r.add_post("/api/v1/admin/auth/start", admin_start)
    r.add_post("/api/v1/admin/auth/verify", admin_verify)
    r.add_post("/api/v1/admin/logout", admin_logout)
    r.add_get("/api/v1/admin/stats", admin_stats)
    r.add_get("/api/v1/admin/config", admin_config_get)
    r.add_put("/api/v1/admin/config", admin_config_put)
    r.add_get("/api/v1/admin/videos", admin_videos)
    r.add_patch("/api/v1/admin/videos/{id}", admin_patch)
    r.add_post("/api/v1/admin/videos/bulk", admin_bulk)
    r.add_post("/api/v1/admin/videos/{id}/thumb", admin_thumb)
    r.add_delete("/api/v1/admin/videos/{id}", admin_delete)
    r.add_get("/api/v1/admin/users", admin_users)
    r.add_post("/api/v1/admin/users/{uid}/premium", admin_user_premium)
    r.add_delete("/api/v1/admin/users/{uid}/premium", admin_user_premium)
    r.add_post("/api/v1/admin/users/{uid}/ban", admin_user_ban)
    r.add_get("/api/v1/admin/audit", admin_audit)
