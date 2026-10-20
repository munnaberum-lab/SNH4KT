import time
from datetime import timedelta
from types import SimpleNamespace as NS

from tests.base import DBCase
from tests.helpers import make_public, video_msg
import info
import state
from database import accounts, files, users
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
    """Owner panel: account ID + password + a one-time code sent to Telegram."""

    async def asyncSetUp(self):
        await seed()
        self.old_admins, self.old_main = info.ADMINS, state.main
        info.ADMINS = [111]
        self.sent = []

        async def send_message(chat, text, **kw):
            self.sent.append((chat, text))
        state.main = NS(send_message=send_message)
        auth.login_limiter, auth.aid_limiter, auth.otp_limiter = RateLimiter(5, 600), RateLimiter(5, 600), RateLimiter(10, 600)
        self.aid, self.pw = await accounts.create(111, "owner_one")
        await accounts.create(222, "just_user")
        self.h = {"X-Requested-With": "fetch", "User-Agent": "UA1"}
        self.cookie = {auth.COOKIE: auth.make_cookie(111, Req(headers=self.h))}

    async def asyncTearDown(self):
        info.ADMINS, state.main = self.old_admins, self.old_main

    def req(self, **kw):
        kw.setdefault("headers", self.h)
        kw.setdefault("cookies", self.cookie)
        return Req(**kw)

    async def test_admin_routes_need_the_cookie(self):
        for call in (api.admin_stats(Req(headers=self.h)), api.admin_videos(Req()), api.admin_config_get(Req()),
                     api.admin_patch(Req(match={"id": "x"}, method="PATCH", headers=self.h)), api.admin_bulk(Req(method="POST", headers=self.h)),
                     api.admin_delete(Req(match={"id": "x"}, method="DELETE", headers=self.h)), api.admin_users(Req()), api.admin_audit(Req())):
            r = await call
            self.assertEqual((r.status, r.data["error"]["code"]), (401, "unauthorized"))
        bad = await api.admin_stats(Req(cookies={auth.COOKIE: "111.1.abc.deadbeef"}, headers=self.h))
        self.assertEqual(bad.status, 401)

    async def test_cookie_is_bound_to_browser_and_time_and_owner_list(self):
        r = self.req()
        self.assertEqual(auth.admin_uid(r), 111)
        self.assertIsNone(auth.admin_uid(Req(cookies=self.cookie, headers={"User-Agent": "other browser"})))
        now = time.time()
        c = auth.make_cookie(111, r, now)
        self.assertEqual(auth.uid_from_cookie(c, r, now + 60), 111)
        self.assertIsNone(auth.uid_from_cookie(c, r, now + info.ADMIN_SESSION_MINUTES * 60 + 5))
        stolen = auth.make_cookie(222, r)  # a valid signature for someone who is not an owner
        self.assertIsNone(auth.uid_from_cookie(stolen, r))
        info.ADMINS = []  # owner removed from ADMINS: cookie stops working at once
        self.assertIsNone(auth.admin_uid(r))

    async def test_mutations_need_the_header(self):
        r = await api.admin_patch(Req(match={"id": "x"}, method="PATCH", cookies=self.cookie, headers={"User-Agent": "UA1"}, body={"hidden": True}))
        self.assertEqual(r.status, 403)

    async def test_login_needs_password_and_telegram_code(self):
        bad = await api.admin_start(Req(method="POST", headers=self.h, body={"id": "owner_one", "password": "wrong"}))
        self.assertEqual(bad.status, 401)
        notowner = await api.admin_start(Req(method="POST", headers=self.h, body={"id": "just_user", "password": "x"}))
        self.assertEqual((notowner.status, notowner.data["error"]["message"]), (401, bad.data["error"]["message"]))  # same answer: owners are not revealed
        self.assertEqual(self.sent, [])
        ok = await api.admin_start(Req(method="POST", headers=self.h, body={"id": "owner_one", "password": self.pw}))
        self.assertEqual(ok.status, 200)
        chat, text = self.sent[-1]
        code = text.split("<code>")[1].split("</code>")[0]
        self.assertEqual((chat, len(code)), (111, 6))
        wrong = await api.admin_verify(Req(method="POST", headers=self.h, body={"challenge": ok.data["challenge"], "code": "000000" if code != "000000" else "111111"}))
        self.assertEqual(wrong.status, 401)
        good = await api.admin_verify(Req(method="POST", headers=self.h, body={"challenge": ok.data["challenge"], "code": code}))
        self.assertEqual(good.status, 200)
        (args, kw), = good.cookies_set
        self.assertTrue(kw["httponly"] and kw["secure"] and kw["samesite"] == "Strict")
        again = await api.admin_verify(Req(method="POST", headers=self.h, body={"challenge": ok.data["challenge"], "code": code}))
        self.assertEqual(again.status, 401)  # a code works once

    async def test_code_locks_after_three_wrong_tries_and_expires(self):
        cid = await auth.start_login("owner_one", self.pw)
        code = self.sent[-1][1].split("<code>")[1].split("</code>")[0]
        for _ in range(3):
            self.assertIsNone(await auth.verify_code(cid, "999999" if code != "999999" else "888888"))
        self.assertIsNone(await auth.verify_code(cid, code))  # even the right code is refused now
        cid2 = await auth.start_login("owner_one", self.pw)
        code2 = self.sent[-1][1].split("<code>")[1].split("</code>")[0]
        await self.db["admin_otp"].update_one({"_id": cid2}, {"$set": {"expires": utcnow() - timedelta(seconds=1)}})
        self.assertIsNone(await auth.verify_code(cid2, code2))

    async def test_login_lockout(self):
        for _ in range(5):
            await api.admin_start(Req(method="POST", headers=self.h, body={"id": "owner_one", "password": "nope"}))
        r = await api.admin_start(Req(method="POST", headers=self.h, body={"id": "owner_one", "password": self.pw}))
        self.assertEqual(r.status, 429)

    async def test_videos_rename_tags_premium_bulk(self):
        d = await files.get("V2")
        r = await api.admin_patch(self.req(match={"id": d["sid"]}, method="PATCH", body={"title": "Brand New Name", "tags": "Action, Hindi, action, #bad!", "premium": True}))
        self.assertEqual(r.status, 200)
        d = await files.get("V2")
        self.assertEqual((d["title"], d["tags"], d["premium"]), ("Brand New Name", ["action", "hindi", "bad"], True))
        self.assertEqual(d["tokens"], ["brand", "new", "name", "action", "hindi", "bad"])
        _, _, total = await files.search("brand new")
        self.assertEqual(total, 1)
        _, _, old = await files.search("long one")  # old name no longer matches
        self.assertEqual(old, 0)
        items, total, _ = await files.list_videos(tag="hindi")
        self.assertEqual([x["_id"] for x in items], ["V2"])
        self.assertEqual((await api.admin_patch(self.req(match={"id": d["sid"]}, method="PATCH", body={"title": "  "}))).status, 400)
        sids = [(await files.get(u))["sid"] for u in ("V0", "V1")]
        r = await api.admin_bulk(self.req(method="POST", body={"ids": sids, "action": "add_tag", "value": "Funny"}))
        self.assertEqual(r.data["changed"], 2)
        self.assertEqual((await files.get("V0"))["tags"], ["funny"])
        await api.admin_bulk(self.req(method="POST", body={"ids": sids, "action": "premium", "value": True}))
        self.assertTrue((await files.get("V1"))["premium"])
        r = await api.admin_bulk(self.req(method="POST", body={"ids": sids, "action": "explode"}))
        self.assertEqual(r.status, 400)
        listing = await api.admin_videos(self.req(query={"premium": "1"}))
        self.assertEqual(len(listing.data["items"]), 3)

    async def test_config_and_audit(self):
        r = await api.admin_config_put(self.req(method="PUT", body={"premium_mode": True, "free_watch_per_day": 3}))
        self.assertEqual((r.data["config"]["premium_mode"], r.data["config"]["free_watch_per_day"]), (True, 3))
        bad = await api.admin_config_put(self.req(method="PUT", body={"free_watch_per_day": -5}))
        self.assertEqual(bad.status, 400)
        self.assertTrue((await api.admin_config_get(self.req())).data["config"]["premium_mode"])
        log = await api.admin_audit(self.req())
        self.assertIn("config", [x["action"] for x in log.data["items"]])

    async def test_users_premium_and_ban(self):
        found = await api.admin_users(self.req(query={"q": "just_user"}))
        self.assertEqual(found.data["items"][0]["uid"], 222)
        r = await api.admin_user_premium(self.req(match={"uid": "222"}, method="POST", body={"days": 5}))
        self.assertEqual(r.status, 200)
        self.assertTrue(await users.is_premium(222))
        self.assertEqual((await api.admin_user_premium(self.req(match={"uid": "222"}, method="POST", body={"days": 0}))).status, 400)
        await api.admin_user_premium(self.req(match={"uid": "222"}, method="DELETE"))
        self.assertFalse(await users.is_premium(222))
        await api.admin_user_ban(self.req(match={"uid": "222"}, method="POST", body={"ban": True}))
        self.assertTrue((await users.ban_status(222))["on"])
        self.assertEqual((await api.admin_user_ban(self.req(match={"uid": "111"}, method="POST", body={"ban": True}))).status, 400)

    async def test_stats_delete_and_kind(self):
        s = await api.admin_stats(self.req())
        self.assertEqual((s.status, s.data["videos"], s.data["hidden"]), (200, 6, 1))
        d = await files.get("V0")
        await api.admin_patch(self.req(match={"id": d["sid"]}, method="PATCH", body={"kind_set": "long"}))
        self.assertEqual((await files.get("V0"))["kind"], "long")
        await api.admin_patch(self.req(match={"id": d["sid"]}, method="PATCH", body={"kind_set": None}))
        self.assertEqual((await files.get("V0"))["kind"], "short")
        self.assertEqual((await api.admin_patch(self.req(match={"id": d["sid"]}, method="PATCH", body={"kind_set": "weird"}))).status, 400)
        r = await api.admin_delete(self.req(match={"id": d["sid"]}, method="DELETE", body={"stream_copy": False}))
        self.assertEqual(r.status, 200)
        self.assertIsNone(await files.get("V0"))

    def test_limiter(self):
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
