"""ffprobe / ffmpeg helpers and the on-disk thumbnail cache."""
import asyncio
import json
import logging
import os
import time

log = logging.getLogger("thumbs")
CACHE_DIR = os.environ.get("THUMB_CACHE_DIR", "/tmp/thumbs")
CACHE_CAP = 200 * 1024 * 1024


def thumb_seek(duration, at):
    """Middle frame for videos under 6 seconds, else THUMB_AT_SECONDS (never past the end)."""
    duration = duration or 0
    if 0 < duration < 6:
        return round(duration / 2, 2)
    if duration and at >= duration:
        return max(round(duration / 2, 2), 0)
    return at


def parse_probe(data):
    """ffprobe JSON -> {w, h, dur, mime?}; swaps w/h when rotated 90/270."""
    out = {"w": 0, "h": 0, "dur": 0}
    for st in data.get("streams", []):
        if st.get("codec_type") == "video":
            w, h = int(st.get("width") or 0), int(st.get("height") or 0)
            rot = 0
            tags = st.get("tags") or {}
            if "rotate" in tags:
                try:
                    rot = int(float(tags["rotate"]))
                except ValueError:
                    pass
            for sd in st.get("side_data_list") or []:
                if "rotation" in sd:
                    try:
                        rot = int(float(sd["rotation"]))
                    except ValueError:
                        pass
            if abs(rot) % 360 in (90, 270):
                w, h = h, w
            out["w"], out["h"] = w, h
            break
    try:
        out["dur"] = int(float((data.get("format") or {}).get("duration") or 0))
    except ValueError:
        pass
    return out


async def _run(*args, timeout=60):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode, out


async def ffprobe(url):
    try:
        rc, out = await _run("ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", url, timeout=45)
        return parse_probe(json.loads(out or b"{}")) if rc == 0 else None
    except Exception as e:  # noqa
        log.warning("ffprobe failed: %s", e)
        return None


async def ffmpeg_thumb(url, seek):
    """One JPEG frame without downloading the whole file."""
    try:
        rc, out = await _run("ffmpeg", "-v", "error", "-ss", str(seek), "-i", url, "-frames:v", "1",
                             "-vf", "scale=640:-2", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1", timeout=60)
        return out if rc == 0 and out else None
    except Exception as e:  # noqa
        log.warning("ffmpeg thumb failed: %s", e)
        return None


# ---- disk cache (cap 200 MB, delete oldest first) -------------------------
def _path(sid):
    return os.path.join(CACHE_DIR, f"{sid}.jpg")


def cache_get(sid):
    p = _path(sid)
    try:
        with open(p, "rb") as f:
            data = f.read()
        os.utime(p, None)
        return data
    except OSError:
        return None


def cache_put(sid, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_path(sid), "wb") as f:
            f.write(data)
        _trim()
    except OSError as e:
        log.warning("thumb cache write failed: %s", e)


def cache_drop(sid):
    try:
        os.remove(_path(sid))
    except OSError:
        pass


def _trim(cap=None):
    cap = cap or CACHE_CAP
    try:
        files = []
        for n in os.listdir(CACHE_DIR):
            p = os.path.join(CACHE_DIR, n)
            st = os.stat(p)
            files.append((st.st_mtime, st.st_size, p))
        total = sum(f[1] for f in files)
        for _, size, p in sorted(files):
            if total <= cap:
                break
            os.remove(p)
            total -= size
    except OSError:
        pass
