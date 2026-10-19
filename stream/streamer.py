"""Telegram byte streaming (HTTP Range) over a media session. Needs pyrofork at runtime."""
import asyncio
import logging
import time

import info
import state
from stream.ranges import CHUNK

log = logging.getLogger("streamer")


class FileGone(Exception):
    pass


class ByteStreamer:
    def __init__(self, client):
        self.client = client
        self._props = {}  # bin message id -> (expires, FileId)

    async def get_file_id(self, bin_id):
        item = self._props.get(bin_id)
        if item and item[0] > time.monotonic():
            return item[1]
        from pyrogram.file_id import FileId
        msg = await self.client.get_messages(info.BIN_CHANNEL, bin_id)
        if not msg or getattr(msg, "empty", False):
            raise FileGone()
        media = None
        for attr in ("video", "document", "audio", "animation"):
            media = getattr(msg, attr, None)
            if media:
                break
        if not media:
            raise FileGone()
        fid = FileId.decode(media.file_id)
        self._props[bin_id] = (time.monotonic() + 30 * 60, fid)
        return fid

    async def media_session(self, fid):
        from pyrogram import raw
        from pyrogram.errors import AuthBytesInvalid
        from pyrogram.session import Auth, Session
        client = self.client
        ms = client.media_sessions.get(fid.dc_id)
        if ms is not None:
            return ms
        test_mode = await client.storage.test_mode()
        if fid.dc_id != await client.storage.dc_id():
            ms = Session(client, fid.dc_id, await Auth(client, fid.dc_id, test_mode).create(), test_mode, is_media=True)
            await ms.start()
            for _ in range(6):
                exported = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=fid.dc_id))
                try:
                    await ms.send(raw.functions.auth.ImportAuthorization(id=exported.id, bytes=exported.bytes))
                    break
                except AuthBytesInvalid:
                    continue
            else:
                await ms.stop()
                raise AuthBytesInvalid
        else:
            ms = Session(client, fid.dc_id, await client.storage.auth_key(), test_mode, is_media=True)
            await ms.start()
        client.media_sessions[fid.dc_id] = ms
        return ms

    @staticmethod
    def location(fid):
        from pyrogram import raw
        from pyrogram.file_id import FileType
        if fid.file_type == FileType.PHOTO:
            return raw.types.InputPhotoFileLocation(id=fid.media_id, access_hash=fid.access_hash,
                                                    file_reference=fid.file_reference, thumb_size=fid.thumbnail_size)
        return raw.types.InputDocumentFileLocation(id=fid.media_id, access_hash=fid.access_hash,
                                                   file_reference=fid.file_reference, thumb_size=fid.thumbnail_size)

    async def yield_file(self, fid, offset, first_cut, last_cut, part_count):
        """Yield the requested bytes chunk by chunk. Stops as soon as the consumer stops iterating."""
        from pyrogram import raw
        from stream.ranges import slice_part
        ms = await self.media_session(fid)
        loc = self.location(fid)
        part = 1
        while part <= part_count:
            try:
                r = await ms.send(raw.functions.upload.GetFile(location=loc, offset=offset, limit=CHUNK))
            except Exception as e:  # noqa
                if type(e).__name__ == "FloodWait":
                    await asyncio.sleep(int(getattr(e, "value", 3)) + 1)
                    r = await ms.send(raw.functions.upload.GetFile(location=loc, offset=offset, limit=CHUNK))
                else:
                    raise
            chunk = getattr(r, "bytes", b"")
            if not chunk:
                break
            yield slice_part(chunk, part, part_count, first_cut, last_cut)
            part += 1
            offset += CHUNK


_streamers = {}


def streamer_for(cid, client):
    if cid not in _streamers:
        _streamers[cid] = ByteStreamer(client)
    return _streamers[cid]


def drop_bin(bin_id):
    for s in _streamers.values():
        s._props.pop(bin_id, None)
