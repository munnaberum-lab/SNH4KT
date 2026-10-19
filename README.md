# Filter Bot + Video Website

A Telegram auto-filter bot (search, filters, pagination, force subscribe, short links, daily verification, premium, referral,
indexing, inline search) with a fast streaming website: **Shorts** (vertical videos, YouTube Shorts style) and **Long** videos,
search with suggestions, and a JSON API. Python 3.11, pyrofork, motor (MongoDB), aiohttp, jinja2. MongoDB stores file details
only, never video bytes.

## 1. Setup (about 15 minutes)

1. **Bot token**: talk to @BotFather, `/newbot`, copy the token -> `BOT_TOKEN`.
2. **API_ID / API_HASH**: log in at my.telegram.org -> API development tools.
3. **MongoDB**: create a free Atlas cluster, add a database user, allow network access `0.0.0.0/0`, copy the connection string
   -> `DATABASE_URI` (URL-encode special characters in the password).
4. **Channels** (the bot must be **administrator** in each):
   - `CHANNELS` - where you post files; new videos/documents are indexed automatically.
   - `BIN_CHANNEL` - private; one stream copy of each file lives here. **Never delete messages in it.**
   - `LOG_CHANNEL` - private; new users/groups, restarts, errors.
5. `ADMINS` - your Telegram user id (space separated for several). `URL` - your public site address.
6. Optional: `AUTH_CHANNEL` (force subscribe), `REQST_CHANNEL`, `SHORTLINK_*`, `VERIFY_*`, `TMDB_API_KEY`, `WEB_ADMIN_PASSWORD`
   (12+ characters), extra bot tokens `MULTI_TOKEN1..N` (add each as admin in `BIN_CHANNEL`).
7. Local test: copy `.env.example` to `.env`, fill it, run `python bot.py`.

If a required variable is missing the app stops and names it. Nothing has a default secret. Booleans: only `1/true/yes/on` is true.

### External services

| Service | Needed for | If missing |
| --- | --- | --- |
| Telegram bot token, API_ID, API_HASH | everything | app will not start |
| MongoDB Atlas URI | all data | app will not start |
| URL shortener (site + API key; generic `https://<site>/api?api=<key>&url=<url>&format=text` style, e.g. gplinks) | short link, verify | those features stay off |
| TMDB API key (v3, free, themoviedb.org) | poster card, "did you mean" | cards and suggestions disabled, search still works |
| Extra bot tokens | faster parallel streaming | one bot streams alone |
| Payment | manual: `PAYMENT_QR` / `PAYMENT_TEXT`, user sends a screenshot, you run `/add_premium <id> 1month` | n/a |

## 2. Deploy on Render (free)

1. Push this folder to GitHub (`.env` is git-ignored).
2. Render -> New -> Web Service -> your repo -> Runtime **Docker**, plan **Free** (or use `render.yaml`).
3. Environment tab -> "Add from .env", or add each variable.
4. Set `URL` to the Render address. Health check path: `/health`.
5. **Keep it awake**: the app pings its own `/health` every `PING_INTERVAL` (240 s), but a sleeping service cannot wake itself.
   Add an **UptimeRobot** HTTP monitor on `https://<your-site>/health` every 5 minutes (optionally also a GitHub Actions cron).

Free plan facts: the first request after sleep takes 30-60 s, 512 MB RAM, limited bandwidth (streaming uses a lot), 750 free hours
per month shared by all free services. If channel posts were missed while asleep, run `/index` again (dedupe makes it safe).

## 3. Using it

- **Index**: post files in `CHANNELS` (automatic) or `/index` (send the last post link or forward it; `/setskip <n>` first to skip).
  Videos are then processed in the background: one stream copy in `BIN_CHANNEL`, size/duration, thumbnail, Shorts/Long kind.
  Files indexed by an older bot: run `/enrich`.
- **Website**: `/` home, `/shorts`, `/long`, `/watch/<id>`, `/search?q=`, `/admin` (only with `WEB_ADMIN_PASSWORD`).
  Links store only a 10-character id; changing `URL` and restarting fixes every link.
- **Bot commands (owner)**: `/stats /users /chats /ban /unban /leave /disable /enable /invite /broadcast /grp_broadcast /logs /restart
  /channel /id /info /index /setskip /delete /deleteall /deletefiles /enrich /thumb /rebuild /link /batch /stream /filter /filters /del /delall
  /gfilter /gfilters /delg /delallg /add_premium /remove_premium /totalrequests /purgerequests`.
  Users: `/start /plan /myplan /refer /trial /request`. Group admins: `/settings /connect /disconnect /connections /set_shortlink /set_fsub /set_caption /set_template /set_tutorial`.
- **Changed bot token / new bot**: run `/rebuild` (new bot must be admin in `BIN_CHANNEL`). Website streaming keeps working meanwhile.
- **Only host files you have the right to share.** `/delete` and the web admin remove a file quickly on request.

## 4. API (`/api/v1`)

`GET /videos` (kind, sort, q, quality, lang, year, page, limit) - `GET /videos/{id}` - `GET /videos/{id}/suggest` - `GET /shorts?after=` -
`POST /videos/{id}/view` - `GET /search/suggest?q=` - `GET /health`. Admin (cookie + `X-Requested-With: fetch`): login, logout, stats, videos,
PATCH/DELETE video, thumb. Errors: `{"error": {"code", "message"}}`. 120 requests/min/IP.

## 5. Tests

`python -m unittest discover -s tests -t .` runs offline (MongoDB is an in-memory stand-in; Telegram and aiohttp are stubbed when not installed).

## 6. Notes and differences from the plan

- The search query uses `{"tokens": {"$all": [<anchored regex>, ...]}}` with real regex objects (MongoDB does not accept `{"$regex": ...}` documents inside `$all`).
- The shortener is a small built-in client (TLS verified, failures logged) instead of the `shortzy` package.
- Plyr is optional: copy `plyr.min.js` and `plyr.css` into `web/static/vendor/plyr/` (see the README there); without them the browser's native controls are used. Nothing loads from a CDN.
- Pin exact dependency versions in `requirements.txt` after checking what is current (`pip index versions pyrofork`).
