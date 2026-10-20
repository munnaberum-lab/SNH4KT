import random
from datetime import timedelta
from types import SimpleNamespace as NS

from tests.base import DBCase
from tests.helpers import make_public, video_msg
from tests.test_04_stream import BLOB, FakeStreamer
from tests.test_05_api_web import Req, seed
import access
import config
import info
import state
from database import accounts, files, social, users
from ingest import ingest
from stream import routes
from utils import utcnow
from web import api, pages, session


async def user_cookie(uid, aid):
    await accounts.create(uid, aid)
    return {session.COOKIE: session.make_cookie(uid, (await accounts.session_info(uid))[1])}


class Config(DBCase):
    async def test_defaults_everything_free(self):
        c = await config.get()
        self.assertEqual((c["premium_mode"], c["require_login"], c["free_watch_per_day"], c["new_account_trial_days"]), (False, False, 0, 0))

    async def test_validation_and_persistence(self):
        c = await config.update({"premium_mode": "on", "free_watch_per_day": "4"})
        self.assertEqual((c["premium_mode"], c["free_watch_per_day"]), (True, 4))
        for bad in ({"free_watch_per_day": -1}, {"free_get_per_day": 99999}, {"nope": 1}, {"premium_mode": "maybe"}, {"new_account_trial_days": "x"}):
            with self.assertRaises(ValueError):
                await config.update(bad)
        config.invalidate()
        self.assertTrue((await config.get())["premium_mode"])   # stored in the database, survives a restart

    async def test_bot_panel_renders(self):
        from plugins import panel
        text, markup = await panel.render()
        self.assertIn("Owner panel", text)
        self.assertTrue(all(len(b.callback_data) <= 64 for r in markup.inline_keyboard for b in r))


class Access(DBCase):
    async def asyncSetUp(self):
        await ingest(video_msg(uid="A", name="Alpha.mp4", size=1))
        await ingest(video_msg(uid="B", name="Beta.mp4", size=2))
        await ingest(video_msg(uid="C", name="Gamma.mp4", size=3))
        for u in "ABC":
            await make_public(files, u)
        self.A, self.B, self.C = [await files.get(u) for u in "ABC"]
        await files.update("C", {"premium": True})
        self.C = await files.get("C")

    async def test_free_mode_everything_open(self):
        self.assertEqual(await access.check(None, self.C), (True, None))
        self.assertEqual(await access.check(5, self.C, "get"), (True, None))

    async def test_require_login(self):
        await config.update({"require_login": True})
        self.assertEqual(await access.check(None, self.A), (False, "login"))
        self.assertEqual(await access.check(5, self.A), (True, None))

    async def test_premium_mode_rules(self):
        await config.update({"premium_mode": True, "free_watch_per_day": 1})
        self.assertEqual(await access.check(None, self.A), (False, "login"))
        self.assertEqual(await access.check(5, self.C), (False, "premium"))        # premium-only video
        self.assertEqual(await access.check(5, self.A, "watch", consume=True), (True, None))
        self.assertEqual(await access.check(5, self.A, "watch", consume=True), (True, None))   # same video again is free
        self.assertEqual(await access.check(5, self.B, "watch", consume=True), (False, "quota"))
        self.assertEqual(await access.check(6, self.B, "watch", consume=True), (True, None))   # other users have their own count
        await users.add_premium(5, timedelta(days=1))
        self.assertEqual(await access.check(5, self.C), (True, None))
        self.assertEqual(await access.check(5, self.B), (True, None))
        old = info.ADMINS
        info.ADMINS = [77]
        try:
            self.assertEqual(await access.check(77, self.C), (True, None))
        finally:
            info.ADMINS = old

    async def test_peek_does_not_use_up_the_limit(self):
        await config.update({"premium_mode": True, "free_watch_per_day": 1})
        for _ in range(3):
            self.assertEqual(await access.check(5, self.A, "watch", consume=False), (True, None))
        self.assertEqual(await access.check(5, self.B, "watch", consume=False), (True, None))

    async def test_new_videos_can_start_premium(self):
        await config.update({"default_new_premium": True})
        await ingest(video_msg(uid="N", name="Newcomer.mp4", size=9))
        self.assertTrue((await files.get("N"))["premium"])


class Delivery(DBCase):
    async def test_bot_blocks_premium_video_and_allows_premium_user(self):
        from plugins import delivery
        await ingest(video_msg(uid="P", name="Paid.mp4", size=5))
        await files.update("P", {"premium": True})
        doc = await files.get("P")
        await accounts.create(1, "free_one")
        await accounts.create(2, "paid_one")
        await users.add_premium(2, timedelta(days=1))
        await config.update({"premium_mode": True})
        sent, said = [], []

        async def send_message(chat, text, **kw):
            said.append(text)
            return NS(id=len(said), chat=NS(id=chat, type="PRIVATE"))

        async def send_cached_media(chat, file_id, **kw):
            sent.append(chat)
            return NS(id=9, chat=NS(id=chat, type="PRIVATE"))
        client = NS(send_message=send_message, send_cached_media=send_cached_media)
        payload = f"file_{doc['sid']}"
        await delivery.handle_payload(client, NS(id=1), 1, payload)
        self.assertEqual(sent, [])
        self.assertTrue(any("ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ" in t for t in said))
        await delivery.handle_payload(client, NS(id=2), 2, payload)
        self.assertEqual(sent, [2])
        await config.update({"premium_mode": False})
        await delivery.handle_payload(client, NS(id=1), 1, payload)   # premium mode off: free for everybody again
        self.assertEqual(sent, [2, 1])

    async def test_bot_daily_download_limit(self):
        from plugins import delivery
        for i in range(3):
            await ingest(video_msg(uid=f"Q{i}", name=f"Movie {i}.mp4", size=10 + i))
        await accounts.create(1, "free_one")
        await config.update({"premium_mode": True, "free_get_per_day": 2})
        sent = []

        async def send_message(chat, text, **kw):
            return NS(id=1, chat=NS(id=chat, type="PRIVATE"))

        async def send_cached_media(chat, file_id, **kw):
            sent.append(file_id)
            return NS(id=9, chat=NS(id=chat, type="PRIVATE"))
        client = NS(send_message=send_message, send_cached_media=send_cached_media)
        for i in range(3):
            await delivery.handle_payload(client, NS(id=1), 1, f"file_{(await files.get(f'Q{i}'))['sid']}")
        self.assertEqual(len(sent), 2)


class Social(DBCase):
    async def asyncSetUp(self):
        await seed()
        info.URL = "https://site.test"
        self.ck1 = await user_cookie(1, "user_one")
        self.ck2 = await user_cookie(2, "user_two")
        self.h = {"X-Requested-With": "fetch"}
        self.sid = (await files.get("V2"))["sid"]
        self.hidden = (await files.get("V4"))["sid"]

    async def test_likes_need_login_and_count_once(self):
        r = await api.like_video(Req(match={"id": self.sid}, method="POST", headers=self.h, body={"like": True}))
        self.assertEqual((r.status, r.data["error"]["code"]), (401, "login_required"))
        r = await api.like_video(Req(match={"id": self.sid}, method="POST", cookies=self.ck1, body={"like": True}))
        self.assertEqual(r.status, 403)                                         # header required
        before = (await files.get("V2")).get("likes", 0)
        for _ in range(2):
            r = await api.like_video(Req(match={"id": self.sid}, method="POST", headers=self.h, cookies=self.ck1, body={"like": True}))
        self.assertEqual(r.data["likes"], before + 1)                           # liking twice counts once
        await api.like_video(Req(match={"id": self.sid}, method="POST", headers=self.h, cookies=self.ck2, body={"like": True}))
        self.assertEqual((await files.get("V2"))["likes"], before + 2)
        r = await api.get_video(Req(match={"id": self.sid}, cookies=self.ck1))
        self.assertTrue(r.data["liked"])
        r = await api.get_video(Req(match={"id": self.sid}, cookies=self.ck2))
        self.assertTrue(r.data["liked"])
        r = await api.get_video(Req(match={"id": self.sid}))
        self.assertFalse(r.data["liked"])
        r = await api.like_video(Req(match={"id": self.sid}, method="POST", headers=self.h, cookies=self.ck1, body={"like": False}))
        self.assertEqual(r.data["likes"], before + 1)
        mine = await api.my_likes(Req(cookies=self.ck2, headers=self.h))
        self.assertEqual([v["id"] for v in mine.data["items"]], [self.sid])
        self.assertEqual((await api.my_likes(Req(cookies=self.ck1, headers=self.h))).data["items"], [])
        self.assertEqual((await api.like_video(Req(match={"id": self.hidden}, method="POST", headers=self.h, cookies=self.ck1, body={}))).status, 404)

    async def test_playlists_are_private_and_limited(self):
        h = self.h
        self.assertEqual((await api.create_playlist(Req(method="POST", headers=h, body={"name": "x"}))).status, 401)
        r = await api.create_playlist(Req(method="POST", headers=h, cookies=self.ck1, body={"name": "  Weekend  ", "video": self.sid}))
        pid = r.data["id"]
        self.assertEqual((await api.create_playlist(Req(method="POST", headers=h, cookies=self.ck1, body={"name": "  "}))).status, 400)
        lst = await api.my_playlists(Req(cookies=self.ck1, headers=h, query={"video": self.sid}))
        self.assertEqual(lst.data["items"], [{"id": pid, "name": "Weekend", "count": 1, "has": True}])
        self.assertEqual((await api.my_playlists(Req(cookies=self.ck2, headers=h))).data["items"], [])
        other = await api.get_playlist(Req(match={"pid": pid}, cookies=self.ck2, headers=h))   # someone else's playlist
        self.assertEqual(other.status, 404)
        self.assertEqual((await api.playlist_add(Req(match={"pid": pid}, method="POST", headers=h, cookies=self.ck2, body={"video": self.sid}))).status, 404)
        second = (await files.get("V3"))["sid"]
        r = await api.playlist_add(Req(match={"pid": pid}, method="POST", headers=h, cookies=self.ck1, body={"video": second}))
        self.assertTrue(r.data["added"])
        r = await api.playlist_add(Req(match={"pid": pid}, method="POST", headers=h, cookies=self.ck1, body={"video": second}))
        self.assertFalse(r.data["added"])
        self.assertEqual((await api.playlist_add(Req(match={"pid": pid}, method="POST", headers=h, cookies=self.ck1, body={"video": self.hidden}))).status, 404)
        got = await api.get_playlist(Req(match={"pid": pid}, cookies=self.ck1, headers=h))
        self.assertEqual([v["id"] for v in got.data["items"]], [self.sid, second])
        await api.playlist_remove(Req(match={"pid": pid, "sid": second}, method="DELETE", headers=h, cookies=self.ck1))
        self.assertEqual(len((await api.get_playlist(Req(match={"pid": pid}, cookies=self.ck1, headers=h))).data["items"]), 1)
        self.assertEqual((await api.remove_playlist(Req(match={"pid": pid}, method="DELETE", headers=h, cookies=self.ck2))).status, 404)
        self.assertEqual((await api.remove_playlist(Req(match={"pid": pid}, method="DELETE", headers=h, cookies=self.ck1))).status, 200)

    async def test_playlist_limits(self):
        for i in range(social.MAX_PLAYLISTS):
            await social.create_playlist(1, f"p{i}")
        with self.assertRaises(social.Limit):
            await social.create_playlist(1, "one too many")

    async def test_locked_flag_and_access_endpoint(self):
        await files.update("V2", {"premium": True})
        await config.update({"premium_mode": True})
        r = await api.get_video(Req(match={"id": self.sid}, cookies=self.ck1))
        self.assertTrue(r.data["locked"] and r.data["premium"])
        a = await api.video_access(Req(match={"id": self.sid}, cookies=self.ck1))
        self.assertEqual((a.data["ok"], a.data["reason"]), (False, "premium"))
        a = await api.video_access(Req(match={"id": self.sid}))
        self.assertEqual(a.data["reason"], "login")
        await users.add_premium(1, timedelta(days=1))
        self.assertTrue((await api.video_access(Req(match={"id": self.sid}, cookies=self.ck1))).data["ok"])
        await config.update({"premium_mode": False})
        r = await api.get_video(Req(match={"id": self.sid}))
        self.assertFalse(r.data["locked"] or r.data["premium"])             # free mode hides all premium marks

    async def test_pages_render_for_everyone(self):
        d = await files.get("V2")
        for who, ck in (("anon", {}), ("user", self.ck1)):
            for name, fn, req in [("login", pages.login_page, Req(path="/login", cookies=ck)), ("library", pages.library_page, Req(path="/library", cookies=ck)),
                                  ("watch", pages.watch_page, Req(path="/watch/x", match={"sid": d["sid"]}, cookies=ck)),
                                  ("search tag", pages.search_page, Req({"tag": "x"}, path="/search", cookies=ck)), ("home", pages.home, Req(path="/", cookies=ck)),
                                  ("shorts", pages.shorts_page, Req(path="/shorts", cookies=ck))]:
                if who == "user" and name == "login":
                    with self.assertRaises(pages.web.HTTPFound):
                        await fn(req)
                    continue
                r = await fn(req)
                self.assertIn("<html", r.text, f"{who} {name}")
        acc = await pages.account_page(Req(path="/account", cookies=self.ck1))
        self.assertIn("user_one", acc.text)
        with self.assertRaises(pages.web.HTTPFound):
            await pages.account_page(Req(path="/account"))
        await files.update("V2", {"premium": True})
        await config.update({"premium_mode": True})
        locked = await pages.watch_page(Req(path="/watch/x", match={"sid": d["sid"]}, cookies=self.ck1))
        self.assertIn("Premium only", locked.text)
        self.assertNotIn('<video id="player"', locked.text)
        self.assertNotIn("data-app=\"vlc\"", locked.text)
        anon = await pages.watch_page(Req(path="/watch/x", match={"sid": d["sid"]}))
        self.assertIn("Login required", anon.text)


class StreamAccess(DBCase):
    async def asyncSetUp(self):
        state.main = NS()
        state.clients.clear()
        state.work_loads.clear()
        routes._doc_cache._d.clear()
        routes._ip_streams.clear()
        self.fs = FakeStreamer()
        self._orig = routes.streamer_for
        routes.streamer_for = lambda cid, client: self.fs
        await ingest(video_msg(size=len(BLOB)))
        await make_public(files, "U1")
        await files.update("U1", {"premium": True})
        self.doc = await files.get("U1")
        self.free_ck = await user_cookie(1, "free_one")
        self.paid_ck = await user_cookie(2, "paid_one")
        await users.add_premium(2, timedelta(days=1))

    async def asyncTearDown(self):
        routes.streamer_for = self._orig

    def req(self, cookies=None, query=None):
        r = Req(cookies=cookies or {}, query=query or {})
        r.headers["Range"] = "bytes=0-99"
        r.remote = "2.2.2.2"
        return r

    async def serve(self, **kw):
        routes._ip_streams.clear()
        return await routes.serve_media(self.req(**kw), self.doc, attachment=False)

    async def test_free_mode_streams_for_everyone(self):
        self.assertEqual((await self.serve()).status, 206)

    async def test_premium_mode_blocks_and_allows(self):
        await config.update({"premium_mode": True})
        r = await self.serve()
        self.assertEqual((r.status, r.data["error"]["code"]), (401, "login_required"))
        r = await self.serve(cookies=self.free_ck)
        self.assertEqual((r.status, r.data["error"]["code"]), (403, "premium_only"))
        r = await self.serve(cookies=self.paid_ck)
        self.assertEqual(r.status, 206)
        self.assertTrue(r.headers["Cache-Control"].startswith("private"))
        self.assertEqual(self.fs.yielded, 1)                                  # nothing was fetched for the blocked requests

    async def test_signed_key_lets_external_players_in(self):
        await config.update({"premium_mode": True})
        key = session.stream_key(2, self.doc["sid"])
        self.assertEqual((await self.serve(query={"k": key})).status, 206)
        self.assertEqual((await self.serve(query={"k": session.stream_key(1, self.doc["sid"])})).status, 403)   # key of a free user
        self.assertEqual((await self.serve(query={"k": key[:-2] + "zz"})).status, 401)
        self.assertEqual((await self.serve(query={"k": session.stream_key(2, "AAAAAAAAAA")})).status, 401)    # key for another video
        self.assertIsNone(session.verify_stream_key(session.stream_key(2, self.doc["sid"], now=1), self.doc["sid"]))   # expired

    async def test_quota_error_for_streams(self):
        await files.update("U1", {"premium": False})
        self.doc = await files.get("U1")
        await ingest(video_msg(uid="U2", name="Other.mp4", size=len(BLOB) + 1))
        await make_public(files, "U2")
        other = await files.get("U2")
        await config.update({"premium_mode": True, "free_watch_per_day": 1})
        self.assertEqual((await self.serve(cookies=self.free_ck)).status, 206)
        routes._ip_streams.clear()
        r = await routes.serve_media(self.req(cookies=self.free_ck), other, attachment=False)
        self.assertEqual((r.status, r.data["error"]["code"]), (403, "quota_reached"))


class SearchQuality(DBCase):
    async def asyncSetUp(self):
        for i, (n, views) in enumerate([("Jailer 2023 Tamil", 5), ("Jailer Making Video", 500), ("Leo 2023 Hindi", 50), ("Lion King 1994", 1)]):
            await ingest(video_msg(uid=f"S{i}", name=n + ".mp4", size=100 + i, mid=i))
            await make_public(files, f"S{i}", views=views, added=utcnow() - timedelta(minutes=i))

    async def test_relevance_beats_popularity_for_exact_matches(self):
        items, total, _ = await files.list_videos(q="jailer 2023", sort="relevance")
        self.assertEqual(items[0]["title"], "Jailer 2023 Tamil")
        items, _, _ = await files.list_videos(q="jailer", sort="relevance")
        self.assertEqual({i["title"] for i in items[:2]}, {"Jailer 2023 Tamil", "Jailer Making Video"})

    async def test_fuzzy_fixes_small_spelling_mistakes(self):
        self.assertEqual(await files.fuzzy("jailr"), "jailer")
        self.assertEqual(await files.fuzzy("lion kng"), "lion king")
        self.assertIsNone(await files.fuzzy("leo"))                 # already fine
        self.assertIsNone(await files.fuzzy("zzzzzzzz"))           # nothing close
        r = await api.list_videos(Req({"q": "jailr"}))
        self.assertEqual((r.data["corrected"], r.data["total"]), ("jailer", 2))
        page = await pages.search_page(Req({"q": "jailr"}, path="/search"))
        self.assertIn("Showing results for", page.text)

    async def test_tags(self):
        await files.update("S2", {"tags": files.clean_tags(["Action", "hindi movie", "Action"]), "tokens": files.retoken({"title": "Leo 2023 Hindi"}, None, ["action"])})
        files.reset_caches()
        self.assertEqual(await files.popular_tags(), ["action", "hindi movie"])
        items, total, _ = await files.list_videos(tag="Action")
        self.assertEqual(total, 1)
        _, _, found = await files.search("act")                       # tags are searchable in the bot too
        self.assertEqual(found, 1)
        r = await api.tags_list(Req())
        self.assertEqual(r.data["tags"][0], "action")
        self.assertEqual(files.clean_tags(["x" * 50, "  ", "A-b"])[1:], ["a-b"])
        with self.assertRaises(pages.web.HTTPFound) as cm:
            await pages.tag_page(Req(match={"tag": "action"}))
        self.assertEqual(cm.exception.location, "/search?tag=action")
