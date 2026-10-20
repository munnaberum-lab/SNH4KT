import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace as NS

from tests.base import DBCase
from tests.test_05_api_web import Req
import config
import info
import state
from database import accounts, referrals, users
from utils import utcnow
from web import api, pages, session
from web.ratelimit import RateLimiter


class Accounts(DBCase):
    async def test_create_rules(self):
        aid, pw = await accounts.create(1, "Rahul_01", "Rahul")
        self.assertEqual(aid, "rahul_01")
        self.assertEqual(len(pw), 10)
        with self.assertRaises(accounts.HasAccount):
            await accounts.create(1, "another_id")                 # one account per Telegram user, ID is final
        with self.assertRaises(accounts.AidTaken):
            await accounts.create(2, "RAHUL_01")                   # IDs are unique, any case
        for bad in ("ab", "1abc", "has space", "x" * 21, "admin", "root", "a-b", ""):
            with self.assertRaises(ValueError, msg=bad):
                await accounts.create(3, bad)
        a, p = await accounts.create(4, accounts.gen_aid())
        self.assertTrue(a.startswith("dx") and len(a) == 8)

    async def test_password_is_hashed_encrypted_and_only_owner_reveal(self):
        aid, pw = await accounts.create(1, "owner_x")
        doc = await accounts.get(1)
        self.assertNotIn(pw, repr(doc))
        self.assertNotEqual(doc["pw_enc"], pw)
        self.assertEqual(await accounts.reveal_password(1), pw)
        self.assertIsNone(await accounts.reveal_password(999))
        self.assertIsNotNone(await accounts.verify("owner_x", pw))
        self.assertIsNone(await accounts.verify("owner_x", pw + "x"))
        self.assertIsNone(await accounts.verify("nobody", pw))

    async def test_password_change_keeps_id_and_logs_out_old_sessions(self):
        aid, pw = await accounts.create(1, "owner_x")
        old_cookie = session.make_cookie(1, (await accounts.session_info(1))[1])
        self.assertEqual((await session.load(Req(cookies={session.COOKIE: old_cookie})))["aid"], "owner_x")
        with self.assertRaises(ValueError):
            await accounts.set_password(1, "short")
        with self.assertRaises(ValueError):
            await accounts.set_password(1, "has a space 123")
        await accounts.set_password(1, "NewPassw0rd!")
        self.assertIsNone(await accounts.verify("owner_x", pw))
        self.assertIsNotNone(await accounts.verify("owner_x", "NewPassw0rd!"))
        self.assertEqual(await accounts.reveal_password(1), "NewPassw0rd!")
        self.assertEqual((await accounts.get(1))["aid"], "owner_x")         # the ID never changes
        self.assertIsNone(await session.load(Req(cookies={session.COOKIE: old_cookie})))

    async def test_session_cookie_rules(self):
        await accounts.create(1, "owner_x")
        ver = (await accounts.session_info(1))[1]
        now = time.time()
        c = session.make_cookie(1, ver, now)
        self.assertEqual(session.parse_cookie(c, now + 100), (1, ver))
        self.assertIsNone(session.parse_cookie(c, now + info.SESSION_DAYS * 86400 + 10))
        self.assertIsNone(session.parse_cookie(c[:-3] + "abc", now))
        self.assertIsNone(session.parse_cookie("1.1.1.zzz", now))
        self.assertIsNone(session.parse_cookie("", now))
        self.assertEqual(session.safe_next("//evil.com"), "/")
        self.assertEqual(session.safe_next("https://evil.com"), "/")
        self.assertEqual(session.safe_next("/\\evil.com"), "/")
        self.assertEqual(session.safe_next("/watch/abc"), "/watch/abc")

    async def test_login_tokens_single_use_and_expiring(self):
        await accounts.create(1, "owner_x")
        t = await accounts.create_login_token(1)
        self.assertEqual(await accounts.consume_login_token(t), 1)
        self.assertIsNone(await accounts.consume_login_token(t))
        t2 = await accounts.create_login_token(1)
        await self.db["login_tokens"].update_one({"_id": t2}, {"$set": {"expires": utcnow() - timedelta(seconds=1)}})
        self.assertIsNone(await accounts.consume_login_token(t2))
        for junk in ("", "x", "a" * 31, "!" * 32, None):
            self.assertIsNone(await accounts.consume_login_token(junk))

    async def test_bot_link_logs_the_browser_in_automatically(self):
        pages.tg_limiter = RateLimiter(30, 600)
        await accounts.create(1, "owner_x")
        tok = await accounts.create_login_token(1)
        with self.assertRaises(pages.web.HTTPFound) as cm:
            await pages.auth_tg(Req(query={"t": tok, "next": "/watch/abc"}))
        self.assertEqual(cm.exception.location, "/watch/abc")
        (args, kw), = cm.exception.cookies_set
        self.assertEqual(args[0], session.COOKIE)
        self.assertTrue(kw["httponly"] and kw["secure"])
        with self.assertRaises(pages.web.HTTPFound) as cm2:      # reuse, junk and open redirects never log anybody in
            await pages.auth_tg(Req(query={"t": tok, "next": "//evil.com"}))
        self.assertEqual((cm2.exception.location, cm2.exception.cookies_set), ("/", []))

    async def test_web_login_api(self):
        api.user_login_limiter, api.user_aid_limiter = RateLimiter(10, 600), RateLimiter(8, 900)
        aid, pw = await accounts.create(1, "owner_x")
        h = {"X-Requested-With": "fetch"}
        self.assertEqual((await api.login(Req(method="POST", body={"id": "owner_x", "password": pw}))).status, 403)  # header needed
        r = await api.login(Req(method="POST", headers=h, body={"id": "owner_x", "password": "bad"}))
        self.assertEqual((r.status, r.data["error"]["code"]), (401, "bad_login"))
        r = await api.login(Req(method="POST", headers=h, body={"id": "OWNER_X", "password": pw}))
        self.assertEqual((r.status, r.data["aid"]), (200, "owner_x"))
        self.assertEqual(r.cookies_set[0][0][0], session.COOKIE)
        for _ in range(9):
            r = await api.login(Req(method="POST", headers=h, body={"id": "owner_x", "password": "bad"}))
        self.assertEqual(r.status, 429)

    async def test_change_password_api_and_me(self):
        api.user_aid_limiter = RateLimiter(8, 900)
        aid, pw = await accounts.create(1, "owner_x")
        ck = {session.COOKIE: session.make_cookie(1, 1)}
        h = {"X-Requested-With": "fetch"}
        me = await api.me(Req(cookies=ck))
        self.assertEqual((me.data["logged_in"], me.data["aid"]), (True, "owner_x"))
        self.assertFalse((await api.me(Req())).data["logged_in"])
        self.assertEqual((await api.change_password(Req(method="POST", headers=h, body={"current": pw, "new": "x"}))).status, 401)  # not logged in
        r = await api.change_password(Req(method="POST", headers=h, cookies=ck, body={"current": "wrong", "new": "GoodPass123"}))
        self.assertEqual(r.status, 401)
        r = await api.change_password(Req(method="POST", headers=h, cookies=ck, body={"current": pw, "new": "short"}))
        self.assertEqual(r.status, 400)
        r = await api.change_password(Req(method="POST", headers=h, cookies=ck, body={"current": pw, "new": "GoodPass123"}))
        self.assertEqual(r.status, 200)
        self.assertEqual(await accounts.reveal_password(1), "GoodPass123")


class FakeClient:
    def __init__(self):
        self.sent = []
        self.n = 0

    async def send_message(self, chat, text, reply_markup=None, **kw):
        self.n += 1
        self.sent.append((chat, text))
        return NS(id=self.n, chat=NS(id=chat, type="PRIVATE"))


class Gate(DBCase):
    async def asyncSetUp(self):
        from plugins import account
        self.account = account
        account.PENDING._d.clear()
        account.AWAIT_ID._d.clear()
        state.bot_username = "testbot"
        self.client = FakeClient()

    def msg(self, uid, text, name="Sam"):
        stopped = []
        replies = []

        async def reply_text(t, **kw):
            replies.append(t)
            return NS(id=1, chat=NS(id=uid, type="PRIVATE"))
        m = NS(from_user=NS(id=uid, first_name=name, last_name=None), chat=NS(id=uid, type="PRIVATE"), text=text, reply_text=reply_text,
               stop_propagation=lambda: stopped.append(True))
        m.stopped, m.replies = stopped, replies
        return m

    async def test_nothing_works_without_an_account(self):
        m = self.msg(50, "/start")
        await self.account.gate_private(self.client, m)
        self.assertTrue(m.stopped)
        self.assertIn("🆔", m.replies[0])
        m2 = self.msg(50, "leo movie")
        await self.account.gate_private(self.client, m2)
        self.assertTrue(m2.stopped)                                  # searches are blocked too
        old = info.ADMINS
        info.ADMINS = [7]
        try:
            m3 = self.msg(7, "/panel")
            await self.account.gate_private(self.client, m3)
            self.assertFalse(m3.stopped)                             # owners are never locked out
        finally:
            info.ADMINS = old

    async def test_account_exists_means_the_gate_opens(self):
        await accounts.create(50, "sam_one")
        m = self.msg(50, "leo")
        await self.account.gate_private(self.client, m)
        self.assertFalse(m.stopped)

    async def test_auto_account_then_resumes_the_original_start_link(self):
        info.REFERRAL_COUNT = 20
        await users.add_user(900, "Owner")                          # referrer already exists
        cfg = await config.update({"premium_mode": True, "new_account_trial_days": 3})
        m = self.msg(60, "/start ref-900")
        await self.account.gate_private(self.client, m)
        self.assertEqual(await referrals.count(900), 0)             # not counted before the account exists
        user = m.from_user
        self.assertTrue(await self.account.create_for(self.client, user, 60, None))
        self.assertTrue(await accounts.has_account(60))
        self.assertEqual(await referrals.count(900), 1)             # counted once, after the account
        self.assertTrue(await users.is_premium(60))                 # free trial from the admin setting
        card = [t for _, t in self.client.sent if "tg-spoiler" in t][0]
        self.assertIn((await accounts.get(60))["aid"], card)
        self.assertIn(await accounts.reveal_password(60), card)
        self.assertIsNone(self.account.PENDING.get(60))

    async def test_choose_own_id_flow(self):
        user = self.msg(61, "x").from_user
        self.account.AWAIT_ID.set(61, True)
        bad = self.msg(61, "9bad id")
        await self.account.gate_private(self.client, bad)
        self.assertFalse(await accounts.has_account(61))
        self.assertTrue(bad.stopped)
        await accounts.create(62, "taken_id")
        taken = self.msg(61, "taken_id")
        await self.account.gate_private(self.client, taken)
        self.assertFalse(await accounts.has_account(61))
        good = self.msg(61, "My_Name")
        await self.account.gate_private(self.client, good)
        self.assertEqual((await accounts.get(61))["aid"], "my_name")

    async def test_account_card_only_goes_to_its_owner(self):
        await accounts.create(70, "owner_a")
        await accounts.create(71, "owner_b")
        await self.account.send_card(self.client, 70, 70)
        chat, text = self.client.sent[-1]
        self.assertEqual(chat, 70)
        self.assertIn("owner_a", text)
        self.assertNotIn("owner_b", text)
        self.assertNotIn(await accounts.reveal_password(71), text)
