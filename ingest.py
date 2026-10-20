"""One function used by auto index, /index, /enrich, /stream and uploads."""
import logging

import config
import enrichment
import info
from database import files
from utils import clean_name, make_tokens, pack_file_id, parse_meta, utcnow

log = logging.getLogger("ingest")


def get_media(msg, allow_audio=False):
    """Return (type, media) for video/document (audio only from source channels)."""
    for attr in ("video", "document") + (("audio",) if allow_audio else ()):
        m = getattr(msg, attr, None)
        if m:
            return attr, m
    return None, None


def compute_kind(is_video, w, h, kind_set=None):
    if not is_video:
        return "none"
    if kind_set in ("short", "long"):
        return kind_set
    return "short" if (w and h and h > w) else "long"


def _caption_html(msg):
    cap = getattr(msg, "caption", None)
    if not cap:
        return ""
    return getattr(cap, "html", None) or str(cap)


def build_doc(msg, source="channel"):
    """Message -> file document (no I/O). Returns None for unsupported media."""
    mtype, media = get_media(msg, allow_audio=(source == "channel"))
    if not media:
        return None
    raw_name = getattr(media, "file_name", None) or (getattr(msg, "caption", None) and str(msg.caption).split("\n")[0]) or media.file_unique_id
    name = clean_name(raw_name) or media.file_unique_id
    caption = _caption_html(msg)
    mime = (getattr(media, "mime_type", None) or "").lower()
    is_video = mtype == "video" or mime.startswith("video/")
    w, h, dur = int(getattr(media, "width", 0) or 0), int(getattr(media, "height", 0) or 0), int(getattr(media, "duration", 0) or 0)
    meta = parse_meta(name)
    chat = getattr(getattr(msg, "chat", None), "id", 0)
    return {
        "_id": media.file_unique_id,
        "file_id": pack_file_id(media.file_id),
        "name": name, "title": name,
        "tokens": make_tokens(name, caption if info.USE_CAPTION_FILTER else ""),
        "size": int(getattr(media, "file_size", 0) or 0), "mime": mime,
        "type": "video" if is_video else ("audio" if mtype == "audio" else "document"),
        "w": w, "h": h, "dur": dur,
        "kind": compute_kind(is_video, w, h),
        **meta,
        "caption": caption,
        "src": {"chat": chat, "msg": getattr(msg, "id", 0)},
        "views": 0, "dl": 0, "likes": 0, "tags": [], "hidden": False, "ok": True,
    }


async def ingest(msg, source="channel"):
    """Returns 'saved', 'duplicate', 'skipped' or 'error'."""
    try:
        doc = build_doc(msg, source)
        if doc is None:
            return "skipped"
        if doc["type"] == "video" and (await config.get())["default_new_premium"]:
            doc["premium"] = True
        result = await files.insert(doc)
        if result == "saved" and doc["type"] == "video":
            enrichment.enqueue(doc["_id"])
        return result
    except Exception as e:  # noqa
        log.exception("ingest failed: %s", e)
        return "error"
