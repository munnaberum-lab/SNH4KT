"""Builds the aiohttp application: middlewares, routes, background keep-alive."""
import asyncio
import logging

from aiohttp import web

import info
from stream import routes as stream_routes
from web import api, pages
from web.ratelimit import RateLimiter

log = logging.getLogger("web")
api_limiter = RateLimiter(120, 60)


@web.middleware
async def middleware(request, handler):
    path = request.path
    if path.startswith("/api/") and not api_limiter.allow(api.client_ip(request)):
        return api.jerr(429, "rate_limited", "Too many requests", {"Retry-After": "30"})
    try:
        resp = await handler(request)
    except web.HTTPNotFound:
        if path.startswith("/api/"):
            return api.jerr(404, "not_found", "Not found")
        return await pages.not_found(request)
    except web.HTTPMethodNotAllowed:
        return api.jerr(405, "method_not_allowed", "Method not allowed") if path.startswith("/api/") else web.Response(status=405)
    except web.HTTPException:
        raise
    except Exception:  # noqa
        log.exception("unhandled error on %s", path)
        if path.startswith("/api/"):
            return api.jerr(503, "unavailable", "Service temporarily unavailable")
        return web.Response(status=503, text="Service temporarily unavailable")
    if path.startswith("/static/"):
        versioned = "v" in request.query  # asset() adds ?v=<hash>, so those can be cached forever
        resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable" if versioned else "public, max-age=300")
    elif path.startswith("/api/v1/admin"):
        resp.headers["Cache-Control"] = "no-store"
    ctype = getattr(resp, "content_type", "") or ""
    if hasattr(resp, "enable_compression") and not path.startswith(("/stream", "/download", "/thumb")) and ctype.startswith(("text/", "application/json", "application/xml")):
        resp.enable_compression()
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


def create_app():
    app = web.Application(middlewares=[middleware], client_max_size=6 * 1024 * 1024)
    api.add_routes(app)  # /health and /api/*
    if info.WEB_ENABLED:
        pages.add_routes(app)
    else:
        async def off(request):
            return web.json_response({"ok": True, "site": "disabled"})
        app.router.add_get("/", off)
    stream_routes.add_routes(app)
    return app


async def start_server(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", info.PORT)
    await site.start()
    log.info("web server listening on 0.0.0.0:%s", info.PORT)
    return runner


async def keep_alive():
    """Ping our own public /health every PING_INTERVAL seconds (Render sleeps after 15 minutes idle)."""
    import aiohttp
    url = f"{info.URL}/health" if info.URL else f"http://127.0.0.1:{info.PORT}/health"
    while True:
        await asyncio.sleep(max(30, info.PING_INTERVAL))
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(url) as r:
                    await r.read()
        except Exception as e:  # noqa
            log.warning("keep-alive failed: %s", e)
