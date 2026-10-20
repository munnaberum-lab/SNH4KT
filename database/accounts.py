"""Website/bot accounts. One account per Telegram user. The ID never changes; only the password can."""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from database import core
from utils import TTLCache, get_secret, rand_b62, utcnow

AID_RE = re.compile(r"^[a-z][a-z0-9_]{2,19}$")
RESERVED = {"admin", "administrator", "root", "support", "telegram", "bot", "owner", "system", "moderator", "staff", "official", "null", "none", "dx"}
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ITERATIONS = 150_000
_has = TTLCache(maxsize=20000, ttl=300)    # uid -> True for users that have an account
_ver = TTLCache(maxsize=20000, ttl=30)     # uid -> (aid, password version)


class AidTaken(Exception):
    pass


class HasAccount(Exception):
    pass


def _c():
    return core.col("accounts")


def _fernet():
    from cryptography.fernet import Fernet
    key = hashlib.sha256(b"account-password-key:" + get_secret().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def valid_aid(aid):
    """Returns (ok, message)."""
    aid = (aid or "").strip().lower()
    if not AID_RE.match(aid):
        return False, "Use 3-20 letters, numbers or _ and start with a letter."
    if aid in RESERVED:
        return False, "That ID is reserved. Choose another."
    return True, ""


def valid_password(pw):
    if not 8 <= len(pw or "") <= 64 or re.search(r"\s", pw):
        return False, "Password must be 8-64 characters with no spaces."
    return True, ""


def gen_aid():
    return "dx" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def gen_password():
    return "".join(secrets.choice(PW_ALPHABET) for _ in range(10))


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITERATIONS).hex()


async def get(uid):
    return await _c().find_one({"_id": uid})


async def get_by_aid(aid):
    return await _c().find_one({"aid": (aid or "").strip().lower()})


async def has_account(uid):
    if _has.get(uid):
        return True
    ok = await _c().find_one({"_id": uid}) is not None
    if ok:
        _has.set(uid, True)
    return ok


async def create(uid, aid, name=""):
    """Returns (aid, password). Raises HasAccount, AidTaken. The ID is final."""
    ok, msg = valid_aid(aid)
    if not ok:
        raise ValueError(msg)
    aid = aid.strip().lower()
    if await get(uid):
        raise HasAccount()
    if await get_by_aid(aid):
        raise AidTaken()
    pw = gen_password()
    salt = secrets.token_hex(16)
    doc = {"_id": uid, "aid": aid, "name": name, "salt": salt, "pw_hash": _hash(pw, salt), "pw_enc": _fernet().encrypt(pw.encode()).decode(),
           "pwv": 1, "created": utcnow()}
    try:
        await _c().insert_one(doc)
    except Exception as e:  # noqa
        if type(e).__name__ == "DuplicateKeyError":
            raise (HasAccount() if await get(uid) else AidTaken())
        raise
    _has.set(uid, True)
    return aid, pw


async def verify(aid, password):
    """Returns the account when aid + password are right, else None (same cost either way)."""
    acc = await get_by_aid(aid)
    salt = acc["salt"] if acc else "00" * 16
    given = _hash(password or "", salt)
    if acc and hmac.compare_digest(given, acc["pw_hash"]):
        return acc
    return None


async def reveal_password(uid):
    """Only ever call this for the account's own owner (the bot does, after checking from_user.id)."""
    acc = await get(uid)
    if not acc:
        return None
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(acc["pw_enc"].encode()).decode()
    except InvalidToken:
        return None


async def set_password(uid, new):
    ok, msg = valid_password(new)
    if not ok:
        raise ValueError(msg)
    salt = secrets.token_hex(16)
    acc = await get(uid)
    if not acc:
        raise ValueError("No account")
    await _c().update_one({"_id": uid}, {"$set": {"salt": salt, "pw_hash": _hash(new, salt), "pw_enc": _fernet().encrypt(new.encode()).decode(),
                                                   "pwv": acc.get("pwv", 1) + 1}})
    _ver.pop(uid)
    return acc.get("pwv", 1) + 1


async def session_info(uid):
    """(aid, pwv) or None. Cached 30 seconds."""
    hit = _ver.get(uid)
    if hit:
        return hit
    acc = await get(uid)
    if not acc:
        return None
    val = (acc["aid"], acc.get("pwv", 1))
    _ver.set(uid, val)
    return val


# ---- one-time login links (bot -> website) -------------------------------
async def create_login_token(uid, ttl_minutes=360):
    token = rand_b62(32)
    await core.col("login_tokens").insert_one({"_id": token, "uid": uid, "used": False, "expires": utcnow() + timedelta(minutes=ttl_minutes)})
    return token


async def consume_login_token(token):
    """uid once for a valid unused token, else None."""
    if not token or not token.isalnum() or len(token) != 32:
        return None
    flt = {"_id": token, "used": False, "expires": {"$gt": utcnow()}}
    doc = await core.col("login_tokens").find_one(flt)
    if not doc:
        return None
    r = await core.col("login_tokens").update_one(flt, {"$set": {"used": True}})
    return doc["uid"] if r.matched_count == 1 else None
