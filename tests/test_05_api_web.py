import time
from datetime import timedelta
from types import SimpleNamespace as NS

from tests.base import DBCase
from tests.helpers import make_public, video_msg
import info
import state
from database import files, users
from ingest import ingest
from utils import utcnow
from web import api, auth, pages, seo
from web.ratelimit import RateLimiter


class Req:
    def __init__(self, query=None, match=None, headers=None, method="GET", cookies=None, body=None, path="/", host="site.test"):
        self.query, self.match_info, self.headers = query or {}, match or {}, headers or {}
        self.method, self.cookies, self._body = method, cookies or {}, body
        self.remote, self.path, self.host, self.scheme = "9.9.9.9", path, host, "https"
        self.content_type = "application/json"
        self.app = {}

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


async def seed():
    state.bot_username = "testbot"
    for i, (name, w, h) in enumerate([("Short One.mp4", 720, 1280), ("Short Two.mp4", 720, 1280), ("Long One 720p.mp4", 1920, 1080),
                                      ("Long Two 1080p.mp4", 1920, 1080), ("Hidden Long.mp4", 1920, 1080), ("Gone Short.mp4", 720, 1280)]):
        await ingest(video_msg(uid=f"V{i}", name=name, w=w, h=h, size=500 + i, mid=i))
        await make_public(files, f"V{i}", kind="short" if h > w else "long", added=utcnow() - timedelta(minutes=10 - i), views=i)
    await files.update("V4", {"hidden": True})
    await files.update("V5", {"ok": False})
    await ingest(video_msg(uid="PDF", name="paper.pdf", mime="application/pdf", w=0, h=0, size=9))  # not a video
    await files.update("PDF", {"type": "document", "kind": "none", "bin": 5})


class Public(DBCase):
    async def asyncSetUp(self):
        await seed()
        info.URL = "https://site.test"

    async def test_hidden_gone_and_non_video_never_leak(self):
        r = await api.list_videos(Req({"kind": "all", "limit": "50"}))
        titles = {i["title"] for i in r.data["items"]}
        self.assertEqual(titles, {"Short One", "Short Two", "Long One 720p", "Long Two 1080p"})
        self.assertEqual(r.data["total"], 4)
        for bad in ("Hidden Long", "Gone Short", "paper"):
            self.assertFalse(any(bad in t for t in titles), bad)
        for sid_doc in ("V4", "V5", "PDF"):
            d = await files.get(sid_doc)
            self.assertEqual((await api.get_video(Req(match={"id": d["sid"]}))).status, 404)
        shorts = await api.shorts_feed(Req({}))
        self.assertEqual(len(shorts.data["items"]), 2)

    async def test_filters_sort_and_validation(self):
        r = await api.list_videos(Req({"kind": "long", "quality": "1080p"}))
        self.assertEqual([i["title"] for i in r.data["items"]], ["Long Two 1080p"])
        r = await api.list_videos(Req({"kind": "short", "sort": "views"}))
        self.assertEqual(r.data["items"][0]["title"], "Short Two")
        r = await api.list_videos(Req({"kind": "bogus"}))
        self.assertEqual((r.status, r.data["error"]["code"]), (400, "bad_request"))
        self.assertIn("message", r.data["error"])
        r = await api.list_videos(Req({"limit": "1", "page": "2"}))
        self.assertEqual((len(r.data["items"]), r.data["has_more"]), (1, True))
        self.assertEqual(r.headers["Cache-Control"], "public, max-age=30")

    async def test_video_object_shape(self):
        d = await files.get("V2")
        r = await api.get_video(Req(match={"id": d["sid"]}))
        v = r.data
        self.assertEqual(v["kind"], "long")
        self.assertEqual(v["urls"]["page"], f"https://site.test/watch/{d['sid']}")
        self.assertEqual(v["urls"]["telegram"], f"https://t.me/testbot?start=v_{d['sid']}")
        self.assertEqual(v["thumb"], f"https://site.test/thumb/{d['sid']}.jpg")
        self.assertTrue(v["playable"])
        self.assertEqual(v["quality"], "720p")
        missing = await api.get_video(Req(match={"id": "AAAAAAAAAA"}))
        self.assertEqual((missing.status, missing.data["error"]["code"]), (404, "not_found"))

    async def test_shorts_cursor_pagination(self):
        first = await api.shorts_feed(Req({"limit": "1"}))
        self.assertEqual(len(first.data["items"]), 1)
        self.assertIsNotNone(first.data["next"])
        second = await api.shorts_feed(Req({"limit": "1", "after": first.data["next"]}))
        self.assertNotEqual(second.data["items"][0]["id"], first.data["items"][0]["id"])
        self.assertIsNone(second.data["next"])
        self.assertEqual((await api.shorts_feed(Req({"after": "!!"}))).status, 400)

    async def test_suggestions_never_empty_and_exclude_current(self):
        d = await files.get("V2")
        r = await api.suggest_for(Req({"limit": "12"}, {"id": d["sid"]}))
        ids = [i["id"] for i in r.data["items"]]
        self.assertEqual(len(ids), 3)  # all other public videos, not the current one, no hidden ones
        self.assertNotIn(d["sid"], ids)
        r2 = await api.suggest_for(Req({"limit": "12", "exclude": ids[0]}, {"id": d["sid"]}))
        self.assertNotIn(ids[0], [i["id"] for i in r2.data["items"]])

    async def test_view_counts_once_per_ip(self):
        d = await files.get("V2")
        before = d["views"]
        r1 = await api.add_view(Req(match={"id": d["sid"]}, method="POST"))
        r2 = await api.add_view(Req(match={"id": d["sid"]}, method="POST"))
        self.assertEqual((r1.data["views"], r2.data["views"]), (before + 1, before + 1))
        self.assertEqual((await files.get("V2"))["views"], before + 1)

    async def test_search_suggest(self):
        self.assertEqual((await api.search_suggest(Req({"q": "a"}))).status, 400)
        r = await api.search_suggest(Req({"q": "lon"}))
        self.assertEqual(len(r.data["items"]), 2)
        self.assertEqual(set(r.data["items"][0]), {"id", "title", "kind", "thumb"})

    async def test_health(self):
        r = await api.health(Req())
        self.assertTrue(r.data["ok"] and r.data["db"])


class Admin(DBCase):
    async def asyncSetUp(self):
        await seed()
        self.old = info.WEB_ADMIN_PASSWORD
        info.WEB_ADMIN_PASSWORD = "correct horse battery"
        auth.login_limiter = RateLimiter(5, 600)
        self.cookie = {auth.COOKIE: auth.make_cookie()}
        self.h = {"X-Requested-With": "fetch"}

    async def asyncTearDown(self):
        info.WEB_ADMIN_PASSWORD = self.old

    async def test_admin_routes_need_the_cookie(self):
        for call in (api.admin_stats(Req()), api.admin_videos(Req()), api.admin_patch(Req(match={"id": "x"}, method="PATCH", headers=self.h)),
                     api.admin_delete(Req(match={"id": "x"}, method="DELETE", headers=self.h)), api.admin_thumb(Req(match={"id": "x"}, method="POST", headers=self.h))):
            r = await call
            self.assertEqual((r.status, r.data["error"]["code"]), (401, "unauthorized"))
        bad = await api.admin_stats(Req(cookies={auth.COOKIE: "1.deadbeef"}))
        self.assertEqual(bad.status, 401)

    async def test_mutations_need_the_header(self):
        r = await api.admin_patch(Req(match={"id": "x"}, method="PATCH", cookies=self.cookie, body={"hidden": True}))
        self.assertEqual(r.status, 403)

    async def test_login_flow_and_lockout(self):
        h = self.h
        r = await api.admin_login(Req(method="POST", headers=h, body={"password": "nope"}))
        self.assertEqual(r.status, 401)
        r = await api.admin_login(Req(method="POST", headers=h, body={"password": "correct horse battery"}))
        self.assertEqual(r.status, 200)
        (args, kw), = r.cookies_set
        self.assertTrue(kw["httponly"] and kw["secure"] and kw["samesite"] == "Strict")
        for _ in range(5):
            r = await api.admin_login(Req(method="POST", headers=h, body={"password": "nope"}))
        self.assertEqual(r.status, 429)

    async def test_stats_patch_delete(self):
        s = await api.admin_stats(Req(cookies=self.cookie))
        self.assertEqual((s.status, s.data["videos"], s.data["hidden"]), (200, 6, 1))
        d = await files.get("V0")
        r = await api.admin_patch(Req(match={"id": d["sid"]}, method="PATCH", headers=self.h, cookies=self.cookie, body={"title": "New title", "kind_set": "long"}))
        self.assertEqual(r.status, 200)
        d = await files.get("V0")
        self.assertEqual((d["title"], d["kind"], d["kind_set"]), ("New title", "long", "long"))
        r = await api.admin_patch(Req(match={"id": d["sid"]}, method="PATCH", headers=self.h, cookies=self.cookie, body={"kind_set": None}))
        self.assertEqual((await files.get("V0"))["kind"], "short")
        r = await api.admin_patch(Req(match={"id": d["sid"]}, method="PATCH", headers=self.h, cookies=self.cookie, body={"kind_set": "weird"}))
        self.assertEqual(r.status, 400)
        listing = await api.admin_videos(Req({"hidden": "1"}, cookies=self.cookie))
        self.assertEqual([i["name"] for i in listing.data["items"]], ["Hidden Long"])
        r = await api.admin_delete(Req(match={"id": d["sid"]}, method="DELETE", headers=self.h, cookies=self.cookie, body={"stream_copy": False}))
        self.assertEqual(r.status, 200)
        self.assertIsNone(await files.get("V0"))

    def test_cookie_and_limiter(self):
        now = time.time()
        c = auth.make_cookie(now)
        self.assertTrue(auth.verify_cookie(c, now + 10))
        self.assertFalse(auth.verify_cookie(c, now + auth.MAX_AGE + 5))
        self.assertFalse(auth.verify_cookie(c[:-2] + "00", now))
        self.assertFalse(auth.verify_cookie("", now))
        rl = RateLimiter(2, 10)
        self.assertEqual([rl.allow("a", 0), rl.allow("a", 1), rl.allow("a", 2), rl.allow("a", 11)], [True, True, False, True])


class Rendering(DBCase):
    async def asyncSetUp(self):
        await seed()
        info.URL = "https://site.test"

    async def test_every_page_renders(self):
        sdoc, ldoc = await files.get("V0"), await files.get("V2")
        cases = [("home", pages.home, Req(path="/")), ("long", pages.long_page, Req(path="/long")),
                 ("search", pages.search_page, Req({"q": "long"}, path="/search")), ("search empty", pages.search_page, Req(path="/search")),
                 ("shorts", pages.shorts_page, Req(path="/shorts")), ("short direct", pages.shorts_page, Req(match={"sid": sdoc["sid"]}, path="/shorts/x")),
                 ("watch", pages.watch_page, Req(match={"sid": ldoc["sid"]}, path="/watch/x")), ("404", pages.not_found, Req(path="/nope"))]
        for name, fn, req in cases:
            r = await fn(req)
            self.assertIn("<html", r.text, name)
        home = (await pages.home(Req(path="/"))).text
        self.assertIn('class="scard"', home)
        self.assertIn("Long One 720p", home)
        self.assertNotIn("Hidden Long", home)
        self.assertNotIn("Gone Short", home)
        watch = (await pages.watch_page(Req(match={"sid": ldoc["sid"]}, path="/watch/x"))).text
        self.assertIn("VideoObject", watch)
        self.assertIn('rel="canonical"', watch)
        self.assertIn(f'/stream/{ldoc["sid"]}', watch)
        sh = (await pages.shorts_page(Req(path="/shorts"))).text
        self.assertIn("shorts.js", sh)
        self.assertNotIn("cdn", watch.lower())

    async def test_redirects_between_kinds(self):
        sdoc, ldoc = await files.get("V0"), await files.get("V2")
        with self.assertRaises(pages.web.HTTPFound):
            await pages.watch_page(Req(match={"sid": sdoc["sid"]}))
        with self.assertRaises(pages.web.HTTPFound):
            await pages.shorts_page(Req(match={"sid": ldoc["sid"]}))
        r = await pages.shorts_page(Req(match={"sid": "AAAAAAAAAA"}))
        self.assertEqual(r.status, 404)

    async def test_seo_files(self):
        self.assertIn("Disallow: /stream", seo.robots_txt("https://x"))
        for p in ("/download", "/thumb", "/api", "/admin"):
            self.assertIn(f"Disallow: {p}", seo.robots_txt("https://x"))
        site = (await pages.sitemap(Req())).text
        self.assertIn("<urlset", site)
        self.assertEqual(site.count("/watch/") + site.count("/shorts/"), 4)

    def test_static_budgets(self):
        import os
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static")
        size = lambda n: os.path.getsize(os.path.join(root, n))
        self.assertLess(size("app.css"), 40 * 1024)
        self.assertLess(size("app.js") + size("cards.js") + size("watch.js"), 60 * 1024)
        self.assertLess(size("shorts.js") + size("cards.js"), 60 * 1024)
