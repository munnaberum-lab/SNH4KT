"""Pure helpers: names, parsing, ids, caches, time, shortener. Stdlib only (aiohttp is imported lazily)."""
import base64
import hashlib
import hmac
import html
import logging
import re
import secrets
import string
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import info

log = logging.getLogger("utils")
B62 = string.digits + string.ascii_letters
_SECRET = None


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def rand_b62(n):
    return "".join(secrets.choice(B62) for _ in range(n))


def get_secret():
    global _SECRET
    if info.SECRET_KEY:
        return info.SECRET_KEY
    if _SECRET is None:
        _SECRET = secrets.token_hex(32)
        log.warning("SECRET_KEY is not set: using a random one (admin sessions and signed links reset on restart)")
    return _SECRET


def sign(*parts, size=8):
    msg = ":".join(str(p) for p in parts).encode()
    return hmac.new(get_secret().encode(), msg, hashlib.sha256).hexdigest()[:size]


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def human_duration(sec):
    sec = int(sec or 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_TIME_RE = re.compile(r"^(\d+)\s*(min|minute|hour|day|week|month|year)s?$", re.I)
_UNITS = {"min": 60, "minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}


def parse_duration(text):
    """'1day' '2 weeks' '1month' -> timedelta, or None."""
    m = _TIME_RE.match((text or "").strip())
    if not m:
        return None
    return timedelta(seconds=int(m.group(1)) * _UNITS[m.group(2).lower()])


def relative_time(dt, now=None):
    now = now or utcnow()
    if not dt:
        return ""
    s = int((now - dt).total_seconds())
    if s < 60:
        return "just now"
    for size, name in ((31536000, "year"), (2592000, "month"), (604800, "week"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = s // size
            return f"{n} {name}{'s' if n != 1 else ''} ago"
    return ""


# ---- booleans -------------------------------------------------------------
def parse_bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ---- name cleaning and parsing -------------------------------------------
_BAD_WORD = re.compile(r"^(@|http|www\.|t\.me)", re.I)


def clean_name(raw):
    """Remove _ . + [] () {}, words starting with @ http www t.me."""
    s = re.sub(r"\.(mp4|mkv|avi|webm|mov|m4v|flv|wmv|mpg|mpeg|ts)\s*$", "", (raw or "").strip(), flags=re.I)
    s = s.replace("_", " ")
    s = re.sub(r"[\[\]\(\)\{\}\+]", " ", s)
    words = [w for w in s.split() if not _BAD_WORD.match(w)]
    s = " ".join(words)
    s = s.replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


def make_tokens(*texts):
    seen, out = set(), []
    for t in texts:
        for w in re.findall(r"[a-z0-9]+", (t or "").lower()):
            if w not in seen:
                seen.add(w)
                out.append(w)
    return out


QUALITIES = ["360p", "480p", "720p", "1080p", "1440p", "2160p"]
LANGUAGES = {
    "malayalam": ["malayalam", "mal"], "tamil": ["tamil", "tam"], "english": ["english", "eng"],
    "hindi": ["hindi", "hin"], "telugu": ["telugu", "tel"], "kannada": ["kannada", "kan"],
}
SEASONS = list(range(1, 11))
EPISODES = [f"E{i:02d}" for i in range(1, 41)]


def years_list():
    return list(range(info.CURRENT_YEAR, 1989, -1))


_Q_RE = re.compile(r"\b(360|480|720|1080|1440|2160)p\b", re.I)
_SE_RE = re.compile(r"\bS(\d{1,2})\s*E(\d{1,3})\b", re.I)
_S_RE = re.compile(r"\b(?:S|season\s*)(\d{1,2})\b", re.I)
_E_RE = re.compile(r"\b(?:E|ep|episode\s*)(\d{1,3})\b", re.I)
_Y_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def parse_meta(name):
    """quality, lang[], year, season, episode parsed once at index time."""
    meta = {"quality": None, "lang": [], "year": None, "season": None, "episode": None}
    m = _Q_RE.search(name or "")
    if m:
        meta["quality"] = m.group(1) + "p"
    low = (name or "").lower()
    for lang, forms in LANGUAGES.items():
        if any(re.search(rf"\b{re.escape(f)}\b", low) for f in forms):
            meta["lang"].append(lang)
    m = _Y_RE.search(name or "")
    if m and 1990 <= int(m.group(1)) <= info.CURRENT_YEAR + 1:
        meta["year"] = int(m.group(1))
    m = _SE_RE.search(name or "")
    if m:
        meta["season"], meta["episode"] = int(m.group(1)), int(m.group(2))
    else:
        s, e = _S_RE.search(name or ""), _E_RE.search(name or "")
        meta["season"] = int(s.group(1)) if s else None
        meta["episode"] = int(e.group(1)) if e else None
    return meta


_STOP = {"in", "upload", "series", "full", "print", "file", "please", "plz", "pls", "send", "movie", "movies",
         "new", "latest", "link", "me", "the", "of", "a", "an", "to", "download", "hd"}


def clean_query(text):
    words = re.findall(r"[^\W_]+", (text or "").lower())
    kept = [w for w in words if w not in _STOP]
    return " ".join(kept or words)


# ---- link and payload helpers ------------------------------------------
def b64e(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def b64d(s):
    """Validate and decode a base64url payload; return None when invalid."""
    if not s or len(s) > 200 or not re.fullmatch(r"[A-Za-z0-9_\-]+", s):
        return None
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()
    except Exception:
        return None


_SID_RE = re.compile(r"^[0-9A-Za-z]{10}$")


def valid_sid(s):
    return bool(s and _SID_RE.match(s))


def pack_file_id(file_id):
    """Compact file id (type, dc, media id, access hash). Falls back to the raw id."""
    try:
        from struct import pack
        from pyrogram.file_id import FileId
        d = FileId.decode(file_id)
        raw = pack("<iiqq", int(d.file_type), d.dc_id, d.media_id, d.access_hash)
        out, n = b"", 0
        for i in raw + bytes([22]) + bytes([4]):
            if i == 0:
                n += 1
            else:
                if n:
                    out += b"\x00" + bytes([n])
                    n = 0
                out += bytes([i])
        return base64.urlsafe_b64encode(out).decode().rstrip("=")
    except Exception:
        return file_id


def media_url(path):
    return f"{info.URL}{path}"


# ---- caches ----------------------------------------------------------------
class TTLCache:
    """Size-limited cache with expiry."""

    def __init__(self, maxsize=1000, ttl=3600):
        self.maxsize, self.ttl, self._d = maxsize, ttl, OrderedDict()

    def get(self, key, default=None):
        item = self._d.get(key)
        if not item:
            return default
        if item[0] < time.monotonic():
            self._d.pop(key, None)
            return default
        self._d.move_to_end(key)
        return item[1]

    def set(self, key, value, ttl=None):
        self._d[key] = (time.monotonic() + (ttl or self.ttl), value)
        self._d.move_to_end(key)
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def pop(self, key, default=None):
        item = self._d.pop(key, None)
        return item[1] if item else default

    def __len__(self):
        return len(self._d)


class Cooldown:
    def __init__(self, seconds):
        self.seconds, self._last = seconds, TTLCache(5000, max(seconds * 5, 10))

    def hit(self, key):
        """True if allowed, False if called too soon."""
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and now - last < self.seconds:
            return False
        self._last.set(key, now)
        return True


# ---- time zone helpers --------------------------------------------------
def today_str():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(info.TZ)).strftime("%Y-%m-%d")
    except Exception:
        return utcnow().strftime("%Y-%m-%d")


# ---- shortener (TLS verified, failures logged) ----------------------------
async def shorten(url, site, api_key):
    """Generic shortener call: https://<site>/api?api=<key>&url=<url>&format=text.
    Returns the original url (and logs) if it fails."""
    if not site or not api_key:
        return url
    import aiohttp
    from urllib.parse import quote
    site = site.replace("https://", "").replace("http://", "").strip("/")
    endpoint = f"https://{site}/api?api={quote(api_key)}&url={quote(url, safe='')}&format=text"
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(endpoint) as r:
                text = (await r.text()).strip()
                if r.status == 200 and text.startswith("http"):
                    return text
                log.warning("shortener %s answered %s", site, r.status)
    except Exception as e:  # noqa
        log.warning("shortener %s failed: %s", site, e)
    return url


def fmt(template, **kw):
    """Safe placeholder replace: unknown {names} and stray braces never raise."""
    return re.sub(r"\{(\w+)\}", lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), template or "")


def to_b36(n):
    n = int(n)
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + out
    return out


def from_b36(s):
    return int(s, 36)
