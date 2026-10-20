"""Runtime settings the owner changes from the bot panel or the website admin panel (stored in MongoDB)."""
import time

import info
from database import settings

KEY = "cfg"
# name: (default, type, min, max)
SCHEMA = {
    "premium_mode": (info.PREMIUM_AND_REFERRAL_MODE, bool, None, None),   # off = everything is free
    "require_login": (False, bool, None, None),                            # website needs an account to play
    "free_watch_per_day": (0, int, 0, 1000),                               # free users, premium mode on. 0 = unlimited
    "free_get_per_day": (0, int, 0, 1000),                                 # file downloads (web + bot). 0 = unlimited
    "new_account_trial_days": (0, int, 0, 365),                            # free premium for every new account
    "default_new_premium": (False, bool, None, None),                      # new videos start as premium-only
}
_cache = {"at": 0.0, "val": None}
TTL = 10


def defaults():
    return {k: v[0] for k, v in SCHEMA.items()}


def clean(key, value):
    """Validate one value. Raises ValueError."""
    if key not in SCHEMA:
        raise ValueError(f"unknown setting {key}")
    default, typ, lo, hi = SCHEMA[key]
    if typ is bool:
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("1", "true", "yes", "on"):
            return True
        if str(value).strip().lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key} must be on or off")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")
    if not lo <= n <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return n


async def get(fresh=False):
    now = time.monotonic()
    if not fresh and _cache["val"] is not None and now - _cache["at"] < TTL:
        return _cache["val"]
    stored = await settings.get(KEY, {}) or {}
    val = defaults()
    for k, v in stored.items():
        if k in SCHEMA:
            try:
                val[k] = clean(k, v)
            except ValueError:
                pass
    _cache.update(at=now, val=val)
    return val


async def update(changes):
    """Validate and save several settings. Returns the new full config."""
    cur = await get(fresh=True)
    new = dict(cur)
    for k, v in changes.items():
        new[k] = clean(k, v)
    await settings.set(KEY, new)
    _cache.update(at=0.0, val=None)
    return await get(fresh=True)


def invalidate():
    _cache.update(at=0.0, val=None)
