from types import SimpleNamespace as NS


def video_msg(uid="U1", name="Leo.2023.720p.Hindi.mp4", size=1000, w=1080, h=1920, dur=30, mime="video/mp4", chat=-1001, mid=1, caption=None):
    media = NS(file_unique_id=uid, file_id=f"FID_{uid}", file_name=name, file_size=size, mime_type=mime, width=w, height=h, duration=dur, thumbs=[])
    return NS(video=media, document=None, audio=None, caption=caption, chat=NS(id=chat), id=mid)


def doc_msg(uid="D1", name="Show.S02E05.1080p.English.mkv", size=5000, mime="video/x-matroska", chat=-1001, mid=2):
    media = NS(file_unique_id=uid, file_id=f"FID_{uid}", file_name=name, file_size=size, mime_type=mime)
    return NS(video=None, document=media, audio=None, caption=None, chat=NS(id=chat), id=mid)


async def make_public(files, uid, kind="long", **extra):
    """Mark a stored file as processed (has a stream copy) so it shows on the website."""
    fields = {"bin": 100 + abs(hash(uid)) % 1000, "key": "k" * 12, "kind": kind}
    fields.update(extra)
    await files.update(uid, fields)
