import asyncio
import random
from types import SimpleNamespace as NS

from tests.base import DBCase
from tests.helpers import make_public, video_msg
import enrichment
import info
import state
from database import files
from ingest import ingest
from stream import clients, routes, thumbs
from stream.ranges import CHUNK, RangeError, chunk_plan, content_disposition, is_playable, parse_range, slice_part

BLOB = bytes(random.Random(1).getrandbits(8) for _ in range(int(3.5 * CHUNK)))


def fetch(start, end):
    """Simulates what the streamer does against Telegram chunks."""
    offset, first, last, parts = chunk_plan(start, end)
    out = b""
    for i in range(1, parts + 1):
        chunk = BLOB[offset + (i - 1) * CHUNK: offset + i * CHUNK]
        out += slice_part(chunk, i, parts, first, last)
    return out


class Ranges(DBCase):
    def test_parse(self):
        self.assertEqual(parse_range(None, 1000), (0, 999, False))
        self.assertEqual(parse_range("bytes=0-99", 1000), (0, 99, True))
        self.assertEqual(parse_range("bytes=900-", 1000), (900, 999, True))
        self.assertEqual(parse_range("bytes=-100", 1000), (900, 999, True))
        self.assertEqual(parse_range("bytes=500-5000", 1000), (500, 999, True))
        for bad in ("bytes=1000-", "bytes=5-2", "bytes=0-1,5-6", "items=0-1", "bytes=a-b", "bytes=-0", "bytes"):
            with self.assertRaises(RangeError, msg=bad):
                parse_range(bad, 1000)

    def test_bytes_are_exact(self):
        size = len(BLOB)
        for start, end in [(0, 99), (5, 5), (CHUNK - 10, CHUNK + 10), (CHUNK, 2 * CHUNK - 1), (100, size - 1), (0, size - 1), (size - 1, size - 1), (CHUNK + 5, CHUNK + 500)]:
            self.assertEqual(fetch(start, end), BLOB[start:end + 1], (start, end))

    def test_helpers(self):
        self.assertTrue(is_playable("video/mp4", 10))
        self.assertFalse(is_playable("video/x-matroska", 10))
        self.assertFalse(is_playable("video/mp4", 3 * 1024 ** 3))
        self.assertIn("filename*=UTF-8''%C3%A9.mp4", content_disposition("é.mp4", True))
        self.assertTrue(content_disposition("a.mp4", False).startswith("inline;"))
        self.assertEqual(thumbs.thumb_seek(4, 3), 2.0)
        self.assertEqual(thumbs.thumb_seek(60, 3), 3)
        self.assertEqual(thumbs.thumb_seek(10, 30), 5.0)

    def test_probe_rotation(self):
        data = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080, "tags": {"rotate": "90"}}], "format": {"duration": "12.7"}}
        self.assertEqual(thumbs.parse_probe(data), {"w": 1080, "h": 1920, "dur": 12})
        data = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}], "format": {}}
        self.assertEqual(thumbs.parse_probe(data)["h"], 1920)


class FakeStreamer:
    def __init__(self):
        self.yielded = 0

    async def get_file_id(self, bin_id):
        return "fid"

    async def yield_file(self, fid, offset, first, last, parts):
        for i in range(1, parts + 1):
            self.yielded += 1
            yield slice_part(BLOB[offset + (i - 1) * CHUNK: offset + i * CHUNK], i, parts, first, last)


class Req:
    def __init__(self, rng=None, method="GET", ip="1.1.1.1"):
        self.headers = {"Range": rng} if rng else {}
        self.method, self.remote, self.query = method, ip, {}


class Serving(DBCase):
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
        self.doc = await files.get("U1")
        await make_public(files, "U1")
        self.sid = self.doc["sid"]

    async def asyncTearDown(self):
        routes.streamer_for = self._orig

    async def test_range_0_99_returns_206_and_100_bytes(self):
        resp = await routes.serve_media(Req("bytes=0-99"), await routes.get_doc(self.sid), attachment=False)
        self.assertEqual(resp.status, 206)
        self.assertEqual(b"".join(resp.chunks), BLOB[:100])
        self.assertEqual(resp.headers["Content-Length"], "100")
        self.assertEqual(resp.headers["Content-Range"], f"bytes 0-99/{len(BLOB)}")
        self.assertEqual(resp.headers["Accept-Ranges"], "bytes")
        self.assertTrue(resp.headers["Content-Disposition"].startswith("inline"))

    async def test_range_inside_a_chunk_and_full_file(self):
        resp = await routes.serve_media(Req(f"bytes={CHUNK + 5}-{CHUNK + 20}"), await routes.get_doc(self.sid), False)
        self.assertEqual(b"".join(resp.chunks), BLOB[CHUNK + 5: CHUNK + 21])
        resp = await routes.serve_media(Req(), await routes.get_doc(self.sid), True)
        self.assertEqual((resp.status, b"".join(resp.chunks)), (200, BLOB))
        self.assertTrue(resp.headers["Content-Disposition"].startswith("attachment"))
        self.assertEqual((await files.get("U1"))["dl"], 1)

    async def test_bad_range_is_416(self):
        resp = await routes.serve_media(Req("bytes=99999999-"), await routes.get_doc(self.sid), False)
        self.assertEqual(resp.status, 416)
        self.assertEqual(resp.headers["Content-Range"], f"bytes */{len(BLOB)}")

    async def test_disconnect_stops_the_stream_and_frees_counters(self):
        doc = await routes.get_doc(self.sid)
        orig = routes.web.StreamResponse.write

        async def boom(self_, chunk):
            raise ConnectionResetError()
        routes.web.StreamResponse.write = boom
        try:
            await routes.serve_media(Req(), doc, False)
        finally:
            routes.web.StreamResponse.write = orig
        self.assertEqual(self.fs.yielded, 1)  # stopped after the first chunk
        self.assertEqual(clients.active_streams(), 0)
        self.assertEqual(sum(routes._ip_streams.values()), 0)

    async def test_limits(self):
        old = info.MAX_STREAMS
        info.MAX_STREAMS = 0
        try:
            r = await routes.serve_media(Req(), await routes.get_doc(self.sid), False)
        finally:
            info.MAX_STREAMS = old
        self.assertEqual((r.status, r.headers.get("Retry-After")), (503, "5"))
        routes._ip_streams["1.1.1.1"] = info.PER_IP_STREAMS
        r = await routes.serve_media(Req(), await routes.get_doc(self.sid), False)
        self.assertEqual(r.status, 429)

    async def test_hidden_and_missing_are_404(self):
        await files.update("U1", {"hidden": True})
        routes.forget(self.sid)
        self.assertIsNone(await routes.get_doc(self.sid))
        self.assertIsNone(await routes.get_doc("nope"))
        self.assertIsNone(await routes.get_doc("zzzzzzzzzz"))


class BinCopy(DBCase):
    async def test_second_click_never_creates_a_second_bin_copy(self):
        await ingest(video_msg())
        doc = await files.get("U1")
        calls = []

        async def send_cached_media(chat, file_id, **kw):
            calls.append(file_id)
            await asyncio.sleep(0.01)
            return NS(id=900 + len(calls), video=NS(width=1080, height=1920, duration=9, mime_type="video/mp4", thumbs=[]), document=None)

        async def delete_messages(*a, **k):
            return True
        client = NS(send_cached_media=send_cached_media, delete_messages=delete_messages)
        results = await asyncio.gather(*[enrichment.ensure_bin(client, doc) for _ in range(6)])
        self.assertEqual(len(calls), 1)
        self.assertEqual({r[0]["bin"] for r in results}, {901})
        self.assertEqual(len([1 for r in results if r[1] is not None]), 1)
        again, sent = await enrichment.ensure_bin(client, doc)
        self.assertEqual((len(calls), sent, again["bin"]), (1, None, 901))
        self.assertEqual(len(again["key"]), 12)

    async def test_process_sets_details_and_kind(self):
        await ingest(video_msg(w=1920, h=1080, name="Wide.mp4", uid="W"))
        sent_media = NS(width=720, height=1280, duration=15, mime_type="video/mp4", thumbs=[])

        async def send_cached_media(chat, file_id, **kw):
            return NS(id=77, video=sent_media, document=None)

        async def send_photo(chat, photo=None, **kw):
            return NS(id=78)

        async def fake_thumb(url, seek):
            return b"\xff\xd8\xff-jpeg"
        orig = enrichment.thumbs.ffmpeg_thumb
        enrichment.thumbs.ffmpeg_thumb = fake_thumb
        try:
            client = NS(send_cached_media=send_cached_media, send_photo=send_photo)
            self.assertTrue(await enrichment.process(client, "W"))
        finally:
            enrichment.thumbs.ffmpeg_thumb = orig
        d = await files.get("W")
        self.assertEqual((d["kind"], d["w"], d["h"], d["dur"], d["bin"], d["thumb"]), ("short", 720, 1280, 15, 77, 78))
