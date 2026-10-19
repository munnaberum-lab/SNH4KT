import importlib
import os
import re
import sys
from types import SimpleNamespace as NS

from tests.base import DBCase
from tests.helpers import make_public, video_msg
import info
import state
from database import files, settings
from ingest import ingest
from web import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Ops(DBCase):
    async def test_changing_url_changes_every_link_and_nothing_in_mongo(self):
        state.bot_username = "b"
        await ingest(video_msg())
        await make_public(files, "U1")
        doc = await files.get("U1")
        before = dict(doc)
        old = info.URL
        try:
            info.URL = "https://one.example"
            a = api.video_obj(doc, api.base_url(NS(headers={}, scheme="https", host="x")))
            info.URL = "https://two.example"
            b = api.video_obj(doc, api.base_url(NS(headers={}, scheme="https", host="x")))
        finally:
            info.URL = old
        self.assertTrue(all(u.startswith("https://one.example") for k, u in a["urls"].items() if k != "telegram"))
        self.assertTrue(all(u.startswith("https://two.example") for k, u in b["urls"].items() if k != "telegram"))
        self.assertEqual(await files.get("U1"), before)
        blob = repr(before)
        self.assertNotIn("one.example", blob)
        self.assertNotIn("https://", blob)

    async def test_heartbeat_gap_is_stored(self):
        self.assertIsNone(await settings.last_beat())
        await settings.beat()
        self.assertIsNotNone(await settings.last_beat())
        await settings.set("index_skip", 5)
        self.assertEqual(await settings.get("index_skip"), 5)

    async def test_rebuild_updates_file_id_by_unique_id(self):
        await ingest(video_msg(uid="STABLE"))
        from plugins import rebuild
        sent = []

        async def send_message(chat, text):
            m = NS(id=11)

            async def delete():
                sent.append("deleted probe")
            m.delete = delete
            return m

        async def get_messages(chat, ids):
            return [NS(id=i, video=NS(file_unique_id="STABLE", file_id="NEWFID"), document=None) for i in ids if i == 5]

        async def edit_text(*a, **k):
            return None
        status = NS(edit_text=edit_text)
        client = NS(send_message=send_message, get_messages=get_messages)
        old = info.BIN_CHANNEL
        info.BIN_CHANNEL = -100777
        try:
            seen, fixed = await rebuild.rebuild_channel(client, -100777, status)
        finally:
            info.BIN_CHANNEL = old
        self.assertEqual((seen, fixed), (1, 1))
        d = await files.get("STABLE")
        self.assertEqual((d["file_id"], d["bin"]), ("NEWFID", 5))

    async def test_multiple_databases_search_merges_and_dedupes(self):
        from database import core
        from tests.fakedb import FakeDB
        second = FakeDB()
        core.use(self.db, [self.db, second])
        await ingest(video_msg(uid="A", name="Alpha One.mp4", size=1))
        await second[info.COLLECTION_NAME].insert_one({"_id": "B", "name": "Alpha Two", "tokens": ["alpha", "two"], "size": 2, "added": None, "sid": "BBBBBBBBBB"})
        docs, _, total = await files.search("alpha")
        self.assertEqual((total, sorted(d["_id"] for d in docs)), (2, ["A", "B"]))
        self.assertEqual((await files.get("B"))["_id"], "B")
        self.assertEqual(await ingest(video_msg(uid="B", name="Other.mp4", size=3)), "duplicate")


class Packaging(DBCase):
    def test_every_plugin_and_module_imports(self):
        mods = ["bot", "texts", "utils", "ingest", "enrichment", "metadata", "bothelpers", "web.server", "web.pages", "stream.routes", "stream.clients", "stream.streamer"]
        mods += [f"plugins.{f[:-3]}" for f in sorted(os.listdir(os.path.join(ROOT, "plugins"))) if f.endswith(".py") and f != "__init__.py"]
        for m in mods:
            importlib.import_module(m)

    def test_no_old_branding_anywhere(self):
        bad = re.compile(r"techvj|tech_vj|kingvj|vj_botz|vj-filter|vjfilter|\bvj\b|vjbot", re.I)
        hits = []
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
            for n in names:
                if n.endswith((".pyc", ".jpg", ".log")):
                    continue
                p = os.path.join(base, n)
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if bad.search(line) and not p.endswith("test_06_ops.py"):
                            hits.append(f"{os.path.relpath(p, ROOT)}:{i}")
        self.assertEqual(hits, [])
        for gone in ("TechVJ", "CloneTechVJ", "Procfile", "heroku.yml", "runtime.txt"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, gone)), gone)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "NOTICE.md")))

    def test_no_secrets_committed(self):
        pat = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{30,}|mongodb(\+srv)?://[^\s'\"<]+:[^\s'\"<@]+@")
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in names:
                if n.endswith((".pyc", ".jpg")):
                    continue
                with open(os.path.join(base, n), encoding="utf-8", errors="ignore") as f:
                    self.assertIsNone(pat.search(f.read()), n)
        self.assertTrue(os.path.exists(os.path.join(ROOT, ".env.example")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".env")))

    def test_every_section7_variable_exists(self):
        names = """BOT_TOKEN API_ID API_HASH DATABASE_URI ADMINS LOG_CHANNEL CHANNELS BIN_CHANNEL URL PORT SITE_NAME SITE_DESCRIPTION OWNER_LNK CHNL_LNK
        GRP_LNK SUPPORT_CHAT PICS DATABASE_NAME COLLECTION_NAME MULTIPLE_DATABASE O_DB_URI F_DB_URI S_DB_URI AI_SPELL_CHECK PM_SEARCH BUTTON_MODE MAX_BTN
        MAX_B_TN IMDB AUTO_FFILTER AUTO_DELETE AUTO_DELETE_SECONDS SPELL_CHECK_REPLY MELCOW_NEW_USERS PROTECT_CONTENT NO_RESULTS_MSG USE_CAPTION_FILTER
        LONG_IMDB_DESCRIPTION CACHE_TIME CUSTOM_FILE_CAPTION IMDB_TEMPLATE AUTH_CHANNEL REQUEST_TO_JOIN_MODE TRY_AGAIN_BTN SHORTLINK_MODE SHORTLINK_URL
        SHORTLINK_API TUTORIAL IS_TUTORIAL VERIFY VERIFY_SHORTLINK_URL VERIFY_SHORTLINK_API VERIFY_TUTORIAL VERIFY_SECOND_SHORTNER VERIFY_SND_SHORTLINK_URL
        VERIFY_SND_SHORTLINK_API PREMIUM_AND_REFERRAL_MODE REFERRAL_COUNT REFERRAL_PREMIUM_TIME PAYMENT_QR PAYMENT_TEXT STREAM_MODE MULTI_TOKENS
        SLEEP_THRESHOLD MAX_STREAMS PING_INTERVAL WEB_ENABLED WEB_DOWNLOAD_PUBLIC WEB_ADMIN_PASSWORD SECRET_KEY PAGE_SIZE SUGGEST_COUNT SHORTS_BATCH
        THUMB_AT_SECONDS TZ TMDB_API_KEY ENRICH_RATE LEGACY_LINKS BACKUP_CHANNEL REQST_CHANNEL INDEX_REQ_CHANNEL FILE_STORE_CHANNEL DELETE_CHANNELS SUPPORT_CHAT_ID""".split()
        self.assertEqual([n for n in names if not hasattr(info, n)], [])

    def test_drop_list_not_built(self):
        banned = ("clone", "rename", "auto_approve", "yt_dl", "lyrics", "openai", "telegraph", "tts")
        for f in os.listdir(os.path.join(ROOT, "plugins")):
            self.assertFalse(any(b in f for b in banned), f)
        req = open(os.path.join(ROOT, "requirements.txt")).read().lower()
        for b in ("cinemagoer", "yt-dlp", "openai", "opencv", "numpy", "googletrans", "gtts", "speedtest"):
            self.assertNotIn(b, req)
