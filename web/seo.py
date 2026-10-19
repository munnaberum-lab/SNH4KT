"""robots.txt, sitemap.xml and JSON-LD."""
import json
from xml.sax.saxutils import escape


def robots_txt(base):
    lines = ["User-agent: *", "Disallow: /stream", "Disallow: /download", "Disallow: /thumb",
             "Disallow: /api", "Disallow: /admin", f"Sitemap: {base}/sitemap.xml", ""]
    return "\n".join(lines)


def sitemap_xml(base, videos):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in ("/", "/shorts", "/long"):
        out.append(f"<url><loc>{escape(base + path)}</loc></url>")
    for v in videos:
        kind = "shorts" if v.get("kind") == "short" else "watch"
        added = v.get("added")
        lastmod = f"<lastmod>{added.strftime('%Y-%m-%d')}</lastmod>" if added else ""
        out.append(f"<url><loc>{escape(base)}/{kind}/{escape(v['sid'])}</loc>{lastmod}</url>")
    out.append("</urlset>")
    return "\n".join(out)


def video_jsonld(base, v, site_name):
    data = {
        "@context": "https://schema.org", "@type": "VideoObject",
        "name": v.get("title") or v.get("name"),
        "description": (v.get("title") or v.get("name") or "")[:200],
        "thumbnailUrl": f"{base}/thumb/{v['sid']}.jpg",
        "contentUrl": f"{base}/stream/{v['sid']}",
        "uploadDate": v["added"].strftime("%Y-%m-%dT%H:%M:%SZ") if v.get("added") else None,
        "duration": _iso_duration(v.get("dur") or 0),
        "publisher": {"@type": "Organization", "name": site_name},
    }
    data = {k: x for k, x in data.items() if x}
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _iso_duration(sec):
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"PT{h}H{m}M{s}S" if h else f"PT{m}M{s}S"
