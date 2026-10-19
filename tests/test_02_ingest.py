import asyncio

from tests.base import DBCase
from tests.helpers import doc_msg, video_msg
import enrichment
from database import files
from ingest import compute_kind, ingest
import utils


class Parsing(DBCase):
    def test_name_parsing(self):
        m = utils.parse_meta("Show S02E05 1080p Hindi English 2023")
        self.assertEqual((m["quality"], m["season"], m["episode"], m["year"]), ("1080p", 2, 5, 2023))
        self.assertEqual(sorted(m["lang"]), ["english", "hindi"])
        self.assertEqual(utils.clean_name("A_B.[@chan] (x) www.site.com t.me/z"), "A B x")
        self.assertEqual(utils.clean_query("please send me the latest Leo movie"), "leo")

    def test_kind(self):
        self.assertEqual(compute_kind(True, 1080, 1920), "short")
        self.assertEqual(compute_kind(True, 1920, 1080), "long")
        self.assertEqual(compute_kind(True, 1920, 1080, "short"), "short")
        self.assertEqual(compute_kind(False, 0, 0), "none")


class Ingest(DBCase):
    async def test_same_file_twice_makes_one_record(self):
        self.assertEqual(await ingest(video_msg()), "saved")
        self.assertEqual(await ingest(video_msg()), "duplicate")
        self.assertEqual(await files.total_count(), 1)

    async def test_same_name_and_size_is_duplicate(self):
        await ingest(video_msg(uid="A"))
        self.assertEqual(await ingest(video_msg(uid="B")), "duplicate")

    async def test_simultaneous_ingest_makes_one_record(self):
        res = await asyncio.gather(*[ingest(video_msg()) for _ in range(8)])
        self.assertEqual(res.count("saved"), 1)
        self.assertEqual(await files.total_count(), 1)

    async def test_document_video_and_unsupported(self):
        self.assertEqual(await ingest(doc_msg()), "saved")
        d = await files.get("D1")
        self.assertEqual((d["type"], d["season"], d["episode"], d["quality"]), ("video", 2, 5, "1080p"))
        self.assertEqual(await ingest(doc_msg(uid="T", name="notes.txt", mime="text/plain")), "saved")
        self.assertEqual((await files.get("T"))["kind"], "none")
        from types import SimpleNamespace as NS
        self.assertEqual(await ingest(NS(video=None, document=None, audio=None)), "skipped")

    async def test_stored_fields(self):
        await ingest(video_msg())
        d = await files.get("U1")
        self.assertTrue(utils.valid_sid(d["sid"]))
        self.assertEqual(d["kind"], "short")
        self.assertEqual(d["tokens"], ["leo", "2023", "720p", "hindi"])
        self.assertNotIn("bin", d)
        self.assertFalse(any(isinstance(v, str) and v.startswith("http") for v in d.values()))

    async def test_video_is_queued_for_enrichment_once(self):
        await ingest(video_msg())
        await ingest(video_msg())
        self.assertEqual(enrichment.progress["total"], 1)
