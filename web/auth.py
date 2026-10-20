"""Admin access: account ID + password, then a one-time code sent to the owner's Telegram. Short session, bound to the browser."""
import hmac
import logging
import secrets
import time
from datetime import timedelta

import info
import state
from database import accounts, core
from utils import rand_b62, sign, utcnow
from web.ratelimit import RateLimiter

log = logging.getLogger("admin-auth")
COOKIE = "adm"
login_limiter = RateLimiter(5, 600)     # per IP
aid_limiter = RateLimiter(5, 600)       # per account ID
otp_limiter = RateLimiter(10, 600)      # per IP


def enabled():
    return bool(info.ADMINS)


def _ua(request):
    return sign("ua", (request.headers.get("User-Agent") or "")[:200], size=10)


def make_cookie(uid, request, now=None):
    ts = int(now or time.time())
    ua = _ua(request)
    return f"{uid}.{ts}.{ua}.{sign('adm', uid, ts, ua, size=32)}"


def uid_from_cookie(value, request, now=None):
    try:
        uid_s, ts_s, ua, sig = (value or "").split(".", 3)
        uid, ts = int(uid_s), int(ts_s)
    except ValueError:
        return None
    now = now or time.time()
    if now - ts > info.ADMIN_SESSION_MINUTES * 60 or ts > now + 60:
        return None
    if not hmac.compare_digest(sig, sign("adm", uid, ts, ua, size=32)) or not hmac.compare_digest(ua, _ua(request)):
        return None
    return uid if uid in info.ADMINS else None


def admin_uid(request):
    return uid_from_cookie(getattr(request, "cookies", {}).get(COOKIE, ""), request) if enabled() else None


def is_admin(request):
    return admin_uid(request) is not None


async def start_login(aid, password):
    """Check ID + password of an owner account, send the one-time code to Telegram. Returns a challenge id or None.
    The same answer (None) is returned for wrong password and for non-admin accounts."""
    acc = await accounts.verify(aid, password)
    if not acc or acc["_id"] not in info.ADMINS or state.main is None:
        return None
    code = f"{secrets.randbelow(10**6):06d}"
    cid = rand_b62(24)
    await core.col("admin_otp").insert_one({"_id": cid, "uid": acc["_id"], "h": sign("otp", cid, code, size=32), "tries": 0,
                                           "expires": utcnow() + timedelta(minutes=5)})
    try:
        await state.main.send_message(acc["_id"], f"🔐 <b>Admin login code</b>\n\n<code>{code}</code>\n\nValid for 5 minutes. If this was not you, change your password with /setpassword.")
    except Exception as e:  # noqa
        log.warning("could not send the admin code: %s", e)
        return None
    return cid


async def verify_code(cid, code):
    """-> admin uid or None. Three tries, single use."""
    row = await core.col("admin_otp").find_one({"_id": cid or ""})
    if not row or row["expires"] < utcnow():
        return None
    if row["tries"] >= 3:
        await core.col("admin_otp").delete_one({"_id": cid})
        return None
    await core.col("admin_otp").update_one({"_id": cid}, {"$set": {"tries": row["tries"] + 1}})
    if not hmac.compare_digest(row["h"], sign("otp", cid, str(code).strip(), size=32)):
        return None
    await core.col("admin_otp").delete_one({"_id": cid})
    return row["uid"]


async def audit(uid, action, detail="", ip=""):
    await core.col("audit").insert_one({"uid": uid, "action": action, "detail": str(detail)[:300], "ip": ip, "at": utcnow()})
