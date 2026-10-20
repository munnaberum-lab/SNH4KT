"""Server-rendered pages (jinja2)."""
import hashlib
import logging
import os

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

import access
import config
import info
import state
from database import accounts, files, social, users
from stream.ranges import is_playable
from utils import human_duration, human_size, relative_time, valid_sid
from web import api, auth, seo, session
from web.ratelimit import RateLimiter

log = logging.getLogger("pages")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
tg_limiter = RateLimiter(30, 600)

env = Environment(loader=FileSystemLoader(os.path.join(HERE, "templates")),
                  autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)


def _views(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M views"
    if n >= 1000:
        return f"{n / 1000:.1f}K views"
    return f"{n} view{'s' if n != 1 else ''}"


def _ago_iso(value):
    from datetime import datetime
    try:
        return relative_time(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return ""


env.filters.update(duration=human_duration, size=human_size, views=_views, ago=relative_time, ago_iso=_ago_iso)
_asset_cache = {}


def asset(name):
    if name not in _asset_cache:
        try:
            with open(os.path.join(STATIC, name), "rb") as f:
                _asset_cache[name] = hashlib.md5(f.read()).hexdigest()[:8]
        except OSError:
            _asset_cache[name] = "0"
    return f"/static/{name}?v={_asset_cache[name]}"


env.globals["asset"] = asset


def render(request, name, status=200, user=None, **ctx):
    base = api.base_url(request)
    meta = {"title": info.SITE_NAME, "description": info.SITE_DESCRIPTION, "canonical": base + request.path,
            "image": base + "/static/logo.svg", "type": "website", "jsonld": None}
    meta.update(ctx.pop("meta", {}))
    has_plyr = os.path.exists(os.path.join(STATIC, "vendor", "plyr", "plyr.min.js"))
    html = env.get_template(name).render(
        site=info.SITE_NAME, base=base, meta=meta, has_plyr=has_plyr, dl_public=info.WEB_DOWNLOAD_PUBLIC, user=user,
        bot=state.bot_username, owner=info.OWNER_LNK, channel=info.CHNL_LNK, request=request, **ctx)
    return web.Response(text=html, status=status, content_type="text/html", charset="utf-8",
                        headers={"Cache-Control": "private, no-cache"} if user else {})


async def decorate(docs, request, user):
    return await api.decorate(docs, api.base_url(request), user)


async def home(request):
    user = await session.load(request)
    shorts, _, _ = await files.list_videos(kind="short", limit=12)
    longs, _, more = await files.list_videos(kind="long", limit=info.PAGE_SIZE)
    total_all = await files.total_count(files.PUBLIC)
    popular = []
    if total_all >= 6:
        pop, _, _ = await files.list_videos(kind="all", sort="views", limit=12)
        popular = await decorate(pop, request, user)
    counts = {"short": await files.total_count({**files.PUBLIC, "kind": "short"}), "long": await files.total_count({**files.PUBLIC, "kind": "long"})}
    return render(request, "home.html", user=user, shorts=await decorate(shorts, request, user), longs=await decorate(longs, request, user),
                  more=more, popular=popular, counts=counts, tags=await files.popular_tags(14))


async def shorts_page(request):
    user = await session.load(request)
    sid = request.match_info.get("sid")
    meta = {}
    if sid:
        d = await files.get_by_sid(sid) if valid_sid(sid) else None
        if not d or d.get("hidden") or d.get("ok") is False or not d.get("bin") or d.get("kind") not in ("short", "long"):
            return await not_found(request)
        if d["kind"] == "long":
            raise web.HTTPFound(f"/watch/{sid}")
        base = api.base_url(request)
        meta = {"title": f"{d.get('title') or d['name']} · {info.SITE_NAME}", "image": f"{base}/thumb/{sid}.jpg",
                "canonical": f"{base}/shorts/{sid}", "type": "video.other"}
    return render(request, "shorts.html", user=user, sid=sid or "", meta=meta, batch=info.SHORTS_BATCH)


def _filters(request):
    q = request.query
    return {"sort": q.get("sort") if q.get("sort") in ("new", "views", "random") else "new",
            "quality": q.get("quality") or "", "lang": q.get("lang") or "", "year": q.get("year") if (q.get("year") or "").isdigit() else ""}


async def long_page(request):
    user = await session.load(request)
    f = _filters(request)
    items, total, more = await files.list_videos(kind="long", sort=f["sort"], quality=f["quality"] or None, lang=f["lang"] or None,
                                                 year=f["year"] or None, limit=info.PAGE_SIZE)
    return render(request, "long.html", user=user, items=await decorate(items, request, user), more=more, total=total, f=f,
                  meta={"title": f"Videos · {info.SITE_NAME}"})


async def watch_page(request):
    user = await session.load(request)
    uid = user["uid"] if user else None
    sid = request.match_info["sid"]
    d = await files.get_by_sid(sid) if valid_sid(sid) else None
    if not d or d.get("hidden") or d.get("ok") is False or not d.get("bin") or d.get("kind") not in ("short", "long"):
        return await not_found(request)
    if d["kind"] == "short":
        raise web.HTTPFound(f"/shorts/{sid}")
    cfg = await config.get()
    ok, reason = await access.check(uid, d, "watch", cfg=cfg)
    base = api.base_url(request)
    v = (await decorate([d], request, user))[0]
    sugg = await decorate(await files.suggestions(d, limit=info.SUGGEST_COUNT), request, user)
    stream_url = v["urls"]["stream"]
    if (cfg["premium_mode"] or cfg["require_login"]) and uid:
        stream_url += "?k=" + session.stream_key(uid, sid)
    meta = {"title": f"{v['title']} · {info.SITE_NAME}", "description": f"Watch {v['title']}", "image": v["thumb"],
            "canonical": v["urls"]["page"], "type": "video.other", "jsonld": seo.video_jsonld(base, d, info.SITE_NAME)}
    return render(request, "watch.html", user=user, v=v, doc=d, suggestions=sugg, meta=meta, locked=None if ok else reason,
                  lock_message=access.MESSAGES.get(reason, ""), ext_url=stream_url,
                  playable=is_playable(d.get("mime"), d.get("size", 0)))


async def search_page(request):
    user = await session.load(request)
    q = (request.query.get("q") or "").strip()
    tag = (request.query.get("tag") or "").strip().lower()[:30]
    kind = request.query.get("kind") if request.query.get("kind") in ("short", "long") else "all"
    f = _filters(request)
    items, total, more, corrected = [], 0, False, None
    if q or tag:
        args = dict(kind=kind, sort="relevance" if q else "new", quality=f["quality"] or None, lang=f["lang"] or None,
                    year=f["year"] or None, tag=tag or None, limit=info.PAGE_SIZE)
        items, total, more = await files.list_videos(q=q or None, **args)
        if q and total == 0:
            corrected = await files.fuzzy(q)
            if corrected:
                items, total, more = await files.list_videos(q=corrected, **args)
    return render(request, "search.html", user=user, q=q, tag=tag, kind=kind, f=f, items=await decorate(items, request, user), total=total,
                  more=more, corrected=corrected, tags=await files.popular_tags(14), meta={"title": f"{tag or q or 'Search'} · {info.SITE_NAME}"})


async def tag_page(request):
    raise web.HTTPFound("/search?tag=" + request.match_info["tag"][:30])


async def login_page(request):
    user = await session.load(request)
    nxt = session.safe_next(request.query.get("next", "/"))
    if user:
        raise web.HTTPFound(nxt)
    return render(request, "login.html", user=None, next=nxt, meta={"title": f"Login · {info.SITE_NAME}"})


async def auth_tg(request):
    """One-time link from the bot: logs the user in and sends them on."""
    nxt = session.safe_next(request.query.get("next", "/"))
    resp = web.HTTPFound(nxt)
    if tg_limiter.allow(api.client_ip(request)):
        uid = await accounts.consume_login_token(request.query.get("t", ""))
        if uid:
            await session.set_cookie(resp, uid)
    raise resp


async def account_page(request):
    user = await session.load(request)
    if not user:
        raise web.HTTPFound("/login?next=/account")
    left = await users.premium_left(user["uid"])
    c = await config.get()
    return render(request, "account.html", user=user, premium_days=left.days if left else 0, is_owner=user["uid"] in info.ADMINS,
                  premium_mode=c["premium_mode"], meta={"title": f"Account · {info.SITE_NAME}"})


async def library_page(request):
    user = await session.load(request)
    return render(request, "library.html", user=user, meta={"title": f"Library · {info.SITE_NAME}"})


async def admin_page(request):
    if not auth.enabled():
        raise web.HTTPNotFound()
    return render(request, "admin.html", user=await session.load(request), admin_in=auth.is_admin(request),
                  meta={"title": f"Admin · {info.SITE_NAME}"})


async def not_found(request):
    user = await session.load(request)
    latest, _, _ = await files.list_videos(kind="all", limit=8)
    return render(request, "404.html", status=404, user=user, latest=await decorate(latest, request, user), meta={"title": f"Not found · {info.SITE_NAME}"})


async def robots(request):
    return web.Response(text=seo.robots_txt(api.base_url(request)), content_type="text/plain")


async def sitemap(request):
    pages, p = [], 1
    while True:
        items, _, more = await files.list_videos(kind="all", page=p, limit=50)
        pages.extend(items)
        if not more or p >= 100:
            break
        p += 1
    return web.Response(text=seo.sitemap_xml(api.base_url(request), pages), content_type="application/xml")


def add_routes(app):
    r = app.router
    r.add_get("/", home)
    r.add_get("/shorts", shorts_page)
    r.add_get("/shorts/{sid}", shorts_page)
    r.add_get("/long", long_page)
    r.add_get("/watch/{sid}", watch_page)
    r.add_get("/search", search_page)
    r.add_get("/tag/{tag}", tag_page)
    r.add_get("/login", login_page)
    r.add_get("/auth/tg", auth_tg)
    r.add_get("/account", account_page)
    r.add_get("/library", library_page)
    r.add_get("/admin", admin_page)
    r.add_get("/robots.txt", robots)
    r.add_get("/sitemap.xml", sitemap)
    r.add_static("/static", STATIC, follow_symlinks=False)
