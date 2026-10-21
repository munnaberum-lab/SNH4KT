"""Website user sessions (signed cookie) and signed stream keys for external players."""
import time

import info
from database import accounts
from utils import from_b36, sign, to_b36

COOKIE = "ut"


def make_cookie(uid, ver, now=None):
    ts = int(now or time.time())
    return f"{uid}.{ver}.{ts}.{sign('ut', uid, ver, ts, size=32)}"


def parse_cookie(value, now=None):
    """-> (uid, ver) when the signature and age are fine, else None."""
    try:
        uid_s, ver_s, ts_s, sig = (value or "").split(".", 3)
        uid, ver, ts = int(uid_s), int(ver_s), int(ts_s)
    except ValueError:
        return None
    now = now or time.time()
    if now - ts > info.SESSION_DAYS * 86400 or ts > now + 60:
        return None
    import hmac
    return (uid, ver) if hmac.compare_digest(sig, sign("ut", uid, ver, ts, size=32)) else None


def _raw_token(request):
    """Mobile app sends 'Authorization: Bearer <token>'; the website sends the cookie."""
    auth = (getattr(request, "headers", None) or {}).get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return getattr(request, "cookies", {}).get(COOKIE, "")


async def make_token(uid):
    """Token for the mobile app (same signed value as the cookie)."""
    cur = await accounts.session_info(uid)
    return make_cookie(uid, cur[1])


async def load(request):
    """The logged in user {'uid','aid'} or None. One cached lookup per 30 seconds."""
    parsed = parse_cookie(_raw_token(request))
    if not parsed:
        return None
    uid, ver = parsed
    cur = await accounts.session_info(uid)
    if not cur or cur[1] != ver:
        return None
    return {"uid": uid, "aid": cur[0]}


async def set_cookie(resp, uid):
    cur = await accounts.session_info(uid)
    resp.set_cookie(COOKIE, make_cookie(uid, cur[1]), max_age=info.SESSION_DAYS * 86400, httponly=True, secure=True,
                    samesite="Lax", path="/")


def clear_cookie(resp):
    resp.del_cookie(COOKIE, path="/")


# ---- stream keys: let VLC / MX Player (no cookies) open a video the user may watch --------------
def stream_key(uid, sid, hours=6, now=None):
    exp = int((now or time.time()) + hours * 3600)
    return f"{to_b36(uid)}.{to_b36(exp)}.{sign('sk', uid, sid, exp, size=24)}"


def verify_stream_key(key, sid, now=None):
    """-> uid or None."""
    try:
        u36, e36, sig = (key or "").split(".", 2)
        uid, exp = from_b36(u36), from_b36(e36)
    except ValueError:
        return None
    import hmac
    if exp < (now or time.time()) or not hmac.compare_digest(sig, sign("sk", uid, sid, exp, size=24)):
        return None
    return uid


def safe_next(path):
    """Only same-site paths are allowed as a redirect target."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or "\n" in path or "\r" in path:
        return "/"
    return path
