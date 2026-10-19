import asyncio
from datetime import timedelta

from tests.base import DBCase
from tests.helpers import video_msg
import info
from database import autodelete, core, files, referrals, users, verify
from ingest import ingest
from utils import utcnow


class Search(DBCase):
    async def asyncSetUp(self):
        for i, n in enumerate(["Leo 2023 720p Hindi.mp4", "Leo 2023 1080p Tamil.mp4", "Jailer 2023 1080p Tamil.mp4", "Show S01E01 480p.mp4"]):
            await ingest(video_msg(uid=f"U{i}", name=n, size=100 + i, mid=i))

    async def test_prefix_search(self):
        docs, nxt, total = await files.search("le")
        self.assertEqual(total, 2)
        docs, _, total = await files.search("leo tam")
        self.assertEqual([d["_id"] for d in docs], ["U1"])
        _, _, total = await files.search("xyz")
        self.assertEqual(total, 0)

    async def test_filters_and_pagination(self):
        _, _, total = await files.search("2023", quality="1080p")
        self.assertEqual(total, 2)
        _, _, total = await files.search("2023", lang="tamil", year=2023)
        self.assertEqual(total, 2)
        docs, nxt, total = await files.search("2023", 0, 2)
        self.assertEqual((len(docs), nxt, total), (2, 2, 3))
        docs, nxt, _ = await files.search("2023", 2, 2)
        self.assertEqual((len(docs), nxt), (1, ""))
        _, _, total = await files.search("show", season=1, episode=1)
        self.assertEqual(total, 1)


class AutoDelete(DBCase):
    async def test_queue_survives_restart(self):
        await autodelete.add(-100, 5, 300)
        await autodelete.add(-100, 6, -1)   # already due
        # a "restart" only loses memory; the data stays in MongoDB
        core.use(self.db)
        due = await autodelete.due()
        self.assertEqual([d["msg"] for d in due], [6])
        await autodelete.remove([d["_id"] for d in due])
        self.assertEqual(await autodelete.due(), [])

    async def test_never_in_channels(self):
        import bothelpers
        from types import SimpleNamespace as NS
        await bothelpers.autodel(NS(chat=NS(id=-1002, type="CHANNEL"), id=1))
        await bothelpers.autodel(NS(chat=NS(id=5, type="PRIVATE"), id=2), seconds=-1)
        self.assertEqual([d["msg"] for d in await autodelete.due()], [2])


class Access(DBCase):
    async def test_verification_survives_restart_and_is_single_use(self):
        token = await verify.create_token(7, "file_abcdefghij")
        core.use(self.db)  # restart: same database, nothing in RAM
        self.assertFalse(await verify.is_verified_today(7))
        self.assertIsNone(await verify.consume_token(8, token))      # wrong user
        res = await verify.consume_token(7, token)
        self.assertEqual(res["pending"], "file_abcdefghij")
        self.assertTrue(await verify.is_verified_today(7))
        self.assertIsNone(await verify.consume_token(7, token))      # used
        core.use(self.db)
        self.assertTrue(await verify.is_verified_today(7))

    async def test_expired_token_is_invalid(self):
        token = await verify.create_token(9)
        await self.db["verify"].update_one({"token": token}, {"$set": {"expires": utcnow() - timedelta(seconds=1)}})
        self.assertIsNone(await verify.consume_token(9, token))

    async def test_verify_return_payload_rules(self):
        from plugins import verify as pv
        token = await verify.create_token(3)
        self.assertIsNone(await pv.handle_return(4, f"verify-3-{token}"))
        self.assertIsNone(await pv.handle_return(3, "verify-3-bad token!"))
        self.assertIsNotNone(await pv.handle_return(3, f"verify-3-{token}"))

    async def test_premium(self):
        self.assertFalse(await users.is_premium(1))
        await users.add_premium(1, timedelta(days=1))
        self.assertTrue(await users.is_premium(1))
        await users.add_premium(1, timedelta(days=1))
        self.assertGreater(await users.premium_left(1), timedelta(days=1, hours=23))
        await users.remove_premium(1)
        self.assertFalse(await users.is_premium(1))

    async def test_referral_reward_triggers_once(self):
        old = info.REFERRAL_COUNT, info.REFERRAL_PREMIUM_TIME
        info.REFERRAL_COUNT, info.REFERRAL_PREMIUM_TIME = 3, "1week"
        try:
            self.assertFalse(await referrals.add_referral(1, 10))
            self.assertFalse(await referrals.add_referral(1, 10))   # same user never counts twice
            self.assertFalse(await referrals.add_referral(1, 1))    # self referral
            self.assertFalse(await referrals.add_referral(1, 11))
            results = await asyncio.gather(referrals.add_referral(1, 12), referrals.add_referral(1, 13))
            self.assertEqual(results.count(True), 1)
            self.assertTrue(await users.is_premium(1))
            self.assertEqual(await referrals.count(1), 0)           # counter reset
        finally:
            info.REFERRAL_COUNT, info.REFERRAL_PREMIUM_TIME = old

    async def test_trial_is_one_time(self):
        self.assertTrue(await users.use_trial(5))
        self.assertFalse(await users.use_trial(5))


class Payloads(DBCase):
    def test_deep_link_payloads(self):
        from plugins import delivery, shortlink
        p = delivery.parse_payload
        self.assertEqual(p("file_AbCdEfGhIj"), ("file", "AbCdEfGhIj", None, None))
        self.assertEqual(p("filep_AbCdEfGhIj_g1234567890"), ("file", "AbCdEfGhIj", True, -1001234567890))
        self.assertEqual(p("v_AbCdEfGhIj")[:2], ("file", "AbCdEfGhIj"))
        self.assertEqual(p("all_Zk39sLp0")[0], "all")
        self.assertEqual(p("DSTORE-abc")[0], "batch")
        for bad in ("", "file_short", "file_" + "x" * 80, "unknown", "all_", "file_AbCdEf!hIj"):
            self.assertIsNone(p(bad), bad)
        link = shortlink.make_payload(42, "file_AbCdEfGhIj")
        self.assertLessEqual(len(link), 64)
        self.assertEqual(shortlink.parse_payload(42, link), "file_AbCdEfGhIj")
        self.assertIsNone(shortlink.parse_payload(43, link))
        self.assertIsNone(shortlink.parse_payload(42, link.replace("file_", "filep")))

    def test_search_helpers(self):
        from plugins import filters_ui, search
        self.assertEqual(search.gsuffix(-1001234567890), "_g1234567890")
        self.assertEqual(search.gsuffix(5), "")
        self.assertEqual(len(filters_ui.options("quality")), 6)
        rows = filters_ui.menu("key12345", "season").inline_keyboard
        self.assertTrue(all(len(b.callback_data) <= 64 for r in rows for b in r))
        self.assertEqual(filters_ui.options("episode")[0], ("E01", "1"))
