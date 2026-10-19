"""Server-rendered pages (jinja2)."""
import hashlib
import logging
import os

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

import info
import state
from database import files
from stream.ranges import is_playable
from utils import human_duration, human_size, relative_time, valid_sid
from web import api, auth, seo

log = logging.getLogger("pages")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

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


def render(request, name, status=200, **ctx):
    base = api.base_url(request)
    meta = {"title": info.SITE_NAME, "description": info.SITE_DESCRIPTION, "canonical": base + request.path,
            "image": base + "/static/logo.svg", "type": "website", "jsonld": None}
    meta.update(ctx.pop("meta", {}))
    has_plyr = os.path.exists(os.path.join(STATIC, "vendor", "plyr", "plyr.min.js"))
    html = env.get_template(name).render(
        site=info.SITE_NAME, base=base, meta=meta, has_plyr=has_plyr, dl_public=info.WEB_DOWNLOAD_PUBLIC,
        bot=state.bot_username, owner=info.OWNER_LNK, channel=info.CHNL_LNK, request=request, **ctx)
    return web.Response(text=html, status=status, content_type="text/html", charset="utf-8")


def objs(docs, base):
    return [api.video_obj(d, base) for d in docs]


async def home(request):
    base = api.base_url(request)
    shorts, _, _ = await files.list_videos(kind="short", limit=12)
    longs, total_long, more = await files.list_videos(kind="long", limit=info.PAGE_SIZE)
    total_all = await files.total_count(files.PUBLIC)
    popular = []
    if total_all >= 6:
        pop, _, _ = await files.list_videos(kind="all", sort="views", limit=12)
        popular = objs(pop, base)
    return render(request, "home.html", shorts=objs(shorts, base), longs=objs(longs, base), more=more, popular=popular)


async def shorts_page(request):
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
    return render(request, "shorts.html", sid=sid or "", meta=meta, batch=info.SHORTS_BATCH)


def _filters(request):
    q = request.query
    return {"sort": q.get("sort") if q.get("sort") in ("new", "views", "random") else "new",
            "quality": q.get("quality") or "", "lang": q.get("lang") or "", "year": q.get("year") if (q.get("year") or "").isdigit() else ""}


async def long_page(request):
    base = api.base_url(request)
    f = _filters(request)
    items, total, more = await files.list_videos(kind="long", sort=f["sort"], quality=f["quality"] or None, lang=f["lang"] or None,
                                                 year=f["year"] or None, limit=info.PAGE_SIZE)
    return render(request, "long.html", items=objs(items, base), more=more, total=total, f=f, meta={"title": f"Long videos · {info.SITE_NAME}"})


async def watch_page(request):
    sid = request.match_info["sid"]
    d = await files.get_by_sid(sid) if valid_sid(sid) else None
    if not d or d.get("hidden") or d.get("ok") is False or not d.get("bin") or d.get("kind") not in ("short", "long"):
        return await not_found(request)
    if d["kind"] == "short":
        raise web.HTTPFound(f"/shorts/{sid}")
    base = api.base_url(request)
    v = api.video_obj(d, base)
    sugg = await files.suggestions(d, limit=info.SUGGEST_COUNT)
    meta = {"title": f"{v['title']} · {info.SITE_NAME}", "description": f"Watch {v['title']}", "image": v["thumb"],
            "canonical": v["urls"]["page"], "type": "video.other", "jsonld": seo.video_jsonld(base, d, info.SITE_NAME)}
    return render(request, "watch.html", v=v, doc=d, suggestions=objs(sugg, base), meta=meta,
                  playable=is_playable(d.get("mime"), d.get("size", 0)))


async def search_page(request):
    base = api.base_url(request)
    q = (request.query.get("q") or "").strip()
    kind = request.query.get("kind") if request.query.get("kind") in ("short", "long") else "all"
    f = _filters(request)
    items, total, more = ([], 0, False)
    if q:
        items, total, more = await files.list_videos(kind=kind, sort="new", q=q, quality=f["quality"] or None,
                                                     lang=f["lang"] or None, year=f["year"] or None, limit=info.PAGE_SIZE)
    return render(request, "search.html", q=q, kind=kind, f=f, items=objs(items, base), total=total, more=more,
                  meta={"title": f"{q or 'Search'} · {info.SITE_NAME}"})


async def admin_page(request):
    if not auth.enabled():
        raise web.HTTPNotFound()
    return render(request, "admin.html", logged_in=auth.is_admin(request))


async def not_found(request):
    base = api.base_url(request)
    latest, _, _ = await files.list_videos(kind="all", limit=8)
    return render(request, "404.html", status=404, latest=objs(latest, base), meta={"title": f"Not found · {info.SITE_NAME}"})


async def robots(request):
    return web.Response(text=seo.robots_txt(api.base_url(request)), content_type="text/plain")


async def sitemap(request):
    pages = []
    p = 1
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
    r.add_get("/admin", admin_page)
    r.add_get("/robots.txt", robots)
    r.add_get("/sitemap.xml", sitemap)
    r.add_static("/static", STATIC, follow_symlinks=False)
