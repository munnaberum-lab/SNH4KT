"""All settings come from environment variables. Never hardcode secrets."""
import os
import re
from datetime import datetime


def _load_dotenv():  # local .env for a PC; Render uses its Environment tab
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        with open(path, encoding="utf-8") as f:
            for line in f.read().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv()


def _bool(name, default=False):
    """Only 1/true/yes/on (any case) is true. The text "False" is False."""
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default=0):
    try:
        return int(str(os.getenv(name, default)).strip())
    except ValueError:
        return default


def _float(name, default=0.0):
    try:
        return float(str(os.getenv(name, default)).strip())
    except ValueError:
        return default


def _str(name, default=""):
    return os.getenv(name, default).strip()


def _ids(name):  # space or comma separated ids
    return [int(x) for x in os.getenv(name, "").replace(",", " ").split() if x.lstrip("-").isdigit()]


def _list(name):
    return [x for x in os.getenv(name, "").replace(",", " ").split() if x]


# ---- required -------------------------------------------------------------
BOT_TOKEN = _str("BOT_TOKEN")
API_ID = _int("API_ID")
API_HASH = _str("API_HASH")
DATABASE_URI = _str("DATABASE_URI")
ADMINS = _ids("ADMINS")
LOG_CHANNEL = _int("LOG_CHANNEL")
CHANNELS = _ids("CHANNELS")
BIN_CHANNEL = _int("BIN_CHANNEL") or LOG_CHANNEL
BIN_CHANNEL_UNSET = not _int("BIN_CHANNEL")

# ---- channels -------------------------------------------------------------
AUTH_CHANNEL = _int("AUTH_CHANNEL")
REQST_CHANNEL = _int("REQST_CHANNEL")
INDEX_REQ_CHANNEL = _int("INDEX_REQ_CHANNEL") or LOG_CHANNEL
FILE_STORE_CHANNEL = _ids("FILE_STORE_CHANNEL")
DELETE_CHANNELS = _ids("DELETE_CHANNELS")
SUPPORT_CHAT_ID = _int("SUPPORT_CHAT_ID")
BACKUP_CHANNEL = _int("BACKUP_CHANNEL")

# ---- site and links -------------------------------------------------------
URL = (_str("URL") or _str("RENDER_EXTERNAL_URL")).rstrip("/")
PORT = _int("PORT", 10000)
SITE_NAME = _str("SITE_NAME", "Video Hub")
SITE_DESCRIPTION = _str("SITE_DESCRIPTION", "Watch shorts and long videos.")
OWNER_LNK = _str("OWNER_LNK")
CHNL_LNK = _str("CHNL_LNK")
GRP_LNK = _str("GRP_LNK")
SUPPORT_CHAT = _str("SUPPORT_CHAT")
PICS = _list("PICS")

# ---- database -------------------------------------------------------------
DATABASE_NAME = _str("DATABASE_NAME", "alfa")
COLLECTION_NAME = _str("COLLECTION_NAME", "omega")
MULTIPLE_DATABASE = _bool("MULTIPLE_DATABASE")
O_DB_URI = _str("O_DB_URI")
F_DB_URI = _str("F_DB_URI")
S_DB_URI = _str("S_DB_URI")

# ---- behaviour switches ---------------------------------------------------
AI_SPELL_CHECK = _bool("AI_SPELL_CHECK", True)
PM_SEARCH = _bool("PM_SEARCH", True)
BUTTON_MODE = _bool("BUTTON_MODE", True)
MAX_BTN = _bool("MAX_BTN", True)
MAX_B_TN = _int("MAX_B_TN", 10)
IMDB = _bool("IMDB", True)
AUTO_FFILTER = _bool("AUTO_FFILTER", True)
AUTO_DELETE = _bool("AUTO_DELETE", True)
AUTO_DELETE_SECONDS = _int("AUTO_DELETE_SECONDS", 300)
SPELL_CHECK_REPLY = _bool("SPELL_CHECK_REPLY", True)
MELCOW_NEW_USERS = _bool("MELCOW_NEW_USERS", True)
PROTECT_CONTENT = _bool("PROTECT_CONTENT", False)
NO_RESULTS_MSG = _bool("NO_RESULTS_MSG", True)
USE_CAPTION_FILTER = _bool("USE_CAPTION_FILTER", False)
LONG_IMDB_DESCRIPTION = _bool("LONG_IMDB_DESCRIPTION", False)
CACHE_TIME = _int("CACHE_TIME", 300)
CUSTOM_FILE_CAPTION = _str("CUSTOM_FILE_CAPTION", "<b>{file_name}</b>\n<code>{file_size}</code>\n{file_caption}")
IMDB_TEMPLATE = _str(
    "IMDB_TEMPLATE",
    "<b>{title}</b> ({year})\n⭐ {rating}/10\n🎭 {genres}\n\n{plot}",
)
SEARCH_COOLDOWN = _float("SEARCH_COOLDOWN", 2.0)

# ---- force subscribe ------------------------------------------------------
REQUEST_TO_JOIN_MODE = _bool("REQUEST_TO_JOIN_MODE")
TRY_AGAIN_BTN = _bool("TRY_AGAIN_BTN", True)

# ---- short link and verify ------------------------------------------------
SHORTLINK_MODE = _bool("SHORTLINK_MODE")
SHORTLINK_URL = _str("SHORTLINK_URL")
SHORTLINK_API = _str("SHORTLINK_API")
TUTORIAL = _str("TUTORIAL")
IS_TUTORIAL = _bool("IS_TUTORIAL")
VERIFY = _bool("VERIFY")
VERIFY_SHORTLINK_URL = _str("VERIFY_SHORTLINK_URL")
VERIFY_SHORTLINK_API = _str("VERIFY_SHORTLINK_API")
VERIFY_TUTORIAL = _str("VERIFY_TUTORIAL")
VERIFY_SECOND_SHORTNER = _bool("VERIFY_SECOND_SHORTNER")
VERIFY_SND_SHORTLINK_URL = _str("VERIFY_SND_SHORTLINK_URL")
VERIFY_SND_SHORTLINK_API = _str("VERIFY_SND_SHORTLINK_API")

# ---- premium and referral -------------------------------------------------
PREMIUM_AND_REFERRAL_MODE = _bool("PREMIUM_AND_REFERRAL_MODE")
REFERRAL_COUNT = _int("REFERRAL_COUNT", 20)
REFERRAL_PREMIUM_TIME = _str("REFERRAL_PREMIUM_TIME", "1month")
PAYMENT_QR = _str("PAYMENT_QR")
PAYMENT_TEXT = _str("PAYMENT_TEXT", "Send the payment, then send the screenshot to the owner.")
FREE_TRIAL_TIME = _str("FREE_TRIAL_TIME")  # e.g. 1day; empty disables the trial

# ---- stream and website ---------------------------------------------------
STREAM_MODE = _bool("STREAM_MODE", True)
MULTI_TOKENS = [
    v.strip()
    for k, v in sorted(os.environ.items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0))
    if re.fullmatch(r"MULTI_TOKEN\d+", k) and v.strip()
]
SLEEP_THRESHOLD = _int("SLEEP_THRESHOLD", 5)
MAX_STREAMS = _int("MAX_STREAMS", 20)
PER_IP_STREAMS = _int("PER_IP_STREAMS", 4)
PING_INTERVAL = _int("PING_INTERVAL", 240)
WEB_ENABLED = _bool("WEB_ENABLED", True)
WEB_DOWNLOAD_PUBLIC = _bool("WEB_DOWNLOAD_PUBLIC", True)
SECRET_KEY = _str("SECRET_KEY")  # REQUIRED: signs sessions and encrypts account passwords. Never change it later.
SESSION_DAYS = _int("SESSION_DAYS", 30)
ADMIN_SESSION_MINUTES = _int("ADMIN_SESSION_MINUTES", 120)
PAGE_SIZE = _int("PAGE_SIZE", 12)
SUGGEST_COUNT = _int("SUGGEST_COUNT", 12)
SHORTS_BATCH = _int("SHORTS_BATCH", 10)
THUMB_AT_SECONDS = _int("THUMB_AT_SECONDS", 3)
ENRICH_RATE = _float("ENRICH_RATE", 1.0)
LEGACY_LINKS = _bool("LEGACY_LINKS")
WORKERS = _int("WORKERS", 16)
TZ = _str("TZ", "Asia/Kolkata")

# ---- metadata api ---------------------------------------------------------
TMDB_API_KEY = _str("TMDB_API_KEY")

CURRENT_YEAR = datetime.utcnow().year


def missing():
    need = {
        "BOT_TOKEN": BOT_TOKEN, "API_ID": API_ID, "API_HASH": API_HASH,
        "DATABASE_URI": DATABASE_URI, "ADMINS": ADMINS,
        "LOG_CHANNEL": LOG_CHANNEL, "CHANNELS": CHANNELS, "SECRET_KEY": SECRET_KEY,
    }
    return [k for k, v in need.items() if not v]
