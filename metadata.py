"""TMDB metadata (poster card, spell-check suggestions). Optional: everything works without a key."""
import logging

import info
from utils import TTLCache

log = logging.getLogger("metadata")
_cache = TTLCache(maxsize=500, ttl=3600)
API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"


async def _get(path, **params):
    if not info.TMDB_API_KEY:
        return None
    import aiohttp
    params["api_key"] = info.TMDB_API_KEY
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(API + path, params=params) as r:
                if r.status != 200:
                    log.warning("TMDB answered %s", r.status)
                    return None
                return await r.json()
    except Exception as e:  # noqa
        log.warning("TMDB failed: %s", e)
        return None


async def search(query, limit=5):
    """Similar titles for spell check. Returns a list of {'title','year','id','media'}."""
    key = ("s", query.lower())
    hit = _cache.get(key)
    if hit is not None:
        return hit
    data = await _get("/search/multi", query=query)
    out = []
    for r in (data or {}).get("results", []):
        if r.get("media_type") not in ("movie", "tv"):
            continue
        title = r.get("title") or r.get("name")
        if not title:
            continue
        date = r.get("release_date") or r.get("first_air_date") or ""
        out.append({"title": title, "year": date[:4], "id": r["id"], "media": r["media_type"]})
        if len(out) >= limit:
            break
    _cache.set(key, out)
    return out


async def card(query):
    """Poster and details for the best match, or None."""
    key = ("c", query.lower())
    hit = _cache.get(key)
    if hit is not None:
        return hit or None
    found = await search(query, 1)
    if not found:
        _cache.set(key, {})
        return None
    f = found[0]
    d = await _get(f"/{f['media']}/{f['id']}")
    if not d:
        return None
    plot = d.get("overview") or ""
    if not info.LONG_IMDB_DESCRIPTION:
        plot = plot[:300] + ("…" if len(plot) > 300 else "")
    out = {
        "title": d.get("title") or d.get("name") or f["title"], "year": f["year"],
        "rating": round(d.get("vote_average") or 0, 1), "genres": ", ".join(g["name"] for g in d.get("genres", [])),
        "plot": plot, "poster": (IMG + d["poster_path"]) if d.get("poster_path") else None,
    }
    _cache.set(key, out)
    return out
