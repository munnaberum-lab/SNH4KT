"""Admin cookie (HMAC signed) and constant-time password check."""
import hmac
import time

import info
from utils import get_secret, sign
from web.ratelimit import RateLimiter

COOKIE = "adm"
MAX_AGE = 12 * 3600
login_limiter = RateLimiter(5, 600)


def enabled():
    return bool(info.WEB_ADMIN_PASSWORD)


def check_password(candidate):
    return enabled() and hmac.compare_digest(str(candidate).encode(), info.WEB_ADMIN_PASSWORD.encode())


def make_cookie(now=None):
    ts = int(now or time.time())
    return f"{ts}.{sign('admin', ts, size=32)}"


def verify_cookie(value, now=None):
    try:
        ts_s, sig = (value or "").split(".", 1)
        ts = int(ts_s)
    except ValueError:
        return False
    if (now or time.time()) - ts > MAX_AGE or ts > (now or time.time()) + 60:
        return False
    return hmac.compare_digest(sig, sign("admin", ts, size=32))


def is_admin(request):
    return enabled() and verify_cookie(request.cookies.get(COOKIE, ""))
