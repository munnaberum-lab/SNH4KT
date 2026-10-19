"""Entry point. Order: check variables, database, web server, Telegram clients, background loops."""
import asyncio
import logging
import logging.config
import os
import sys

import info


def fail_if_missing():
    miss = info.missing()
    if miss:
        print(f"Missing environment variables: {', '.join(miss)}. Add them in Render, Environment.", file=sys.stderr)
        sys.exit(1)


def setup_logging():
    handlers = {"console": {"class": "logging.StreamHandler", "formatter": "f"}}
    root = ["console"]
    try:
        handlers["file"] = {"class": "logging.handlers.RotatingFileHandler", "filename": os.environ.get("LOG_FILE", "bot.log"),
                            "maxBytes": 2_000_000, "backupCount": 1, "formatter": "f", "encoding": "utf-8"}
        root.append("file")
    except Exception:  # noqa
        pass
    logging.config.dictConfig({
        "version": 1, "disable_existing_loggers": False,
        "formatters": {"f": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s", "datefmt": "%H:%M:%S"}},
        "handlers": handlers, "root": {"level": "INFO", "handlers": root},
        "loggers": {"pyrogram": {"level": "WARNING"}, "aiohttp.access": {"level": "WARNING"}},
    })


log = logging.getLogger("bot")


async def autodelete_loop(client):
    """Every 20 seconds delete the messages that are due. The queue lives in MongoDB, so it survives restarts."""
    from database import autodelete
    while True:
        try:
            due = await autodelete.due(200)
            by_chat = {}
            for d in due:
                by_chat.setdefault(d["chat"], []).append(d)
            for chat, docs in by_chat.items():
                ids = [d["msg"] for d in docs]
                try:
                    await client.delete_messages(chat, ids)
                except Exception as e:  # noqa
                    if type(e).__name__ == "FloodWait":
                        await asyncio.sleep(int(getattr(e, "value", 5)) + 1)
                        continue
                    log.info("auto delete in %s failed: %s", chat, type(e).__name__)
                await autodelete.remove([d["_id"] for d in docs])
        except Exception as e:  # noqa
            log.warning("auto delete loop: %s", e)
        await asyncio.sleep(20)


async def heartbeat_loop(client):
    from database import settings
    import texts
    from bothelpers import send_log
    from utils import utcnow
    last = await settings.last_beat()
    gap = (utcnow() - last).total_seconds() / 60 if last else 0
    extra = texts.OFFLINE_LOG.format(minutes=int(gap)) if gap > 5 else ""
    await send_log(client, texts.RESTART_LOG.format(extra=extra))
    while True:
        try:
            await settings.beat()
        except Exception as e:  # noqa
            log.warning("heartbeat failed: %s", e)
        await asyncio.sleep(60)


async def main():
    import state
    from database import core
    from pyrogram import Client, enums, idle
    from web import server
    import enrichment

    if info.BIN_CHANNEL_UNSET:
        log.warning("BIN_CHANNEL is not set: using LOG_CHANNEL. Use a separate private channel so stream copies are never deleted.")
    if not info.URL:
        log.warning("URL is not set (and no RENDER_EXTERNAL_URL): links will use the request host")
    if info.VERIFY and not info.VERIFY_SHORTLINK_URL:
        log.warning("VERIFY is on but VERIFY_SHORTLINK_URL is empty: verification links will not be shortened")

    log.info("step 1/5 connecting to MongoDB")
    await core.init()
    log.info("step 2/5 starting the web server on port %s", info.PORT)
    runner = await server.start_server(server.create_app())

    log.info("step 3/5 starting Telegram")
    bot = Client("filterbot", api_id=info.API_ID, api_hash=info.API_HASH, bot_token=info.BOT_TOKEN, workers=info.WORKERS,
                 sleep_threshold=info.SLEEP_THRESHOLD, plugins={"root": "plugins"}, in_memory=True, parse_mode=enums.ParseMode.HTML)
    await bot.start()
    state.main = bot
    state.clients[0], state.work_loads[0] = bot, 0
    state.bot_username = bot.me.username
    log.info("logged in as @%s", state.bot_username)
    from stream.clients import start_extra_clients
    await start_extra_clients()

    log.info("step 4/5 starting background loops")
    from plugins.index import resume_jobs
    tasks = [asyncio.create_task(enrichment.worker()), asyncio.create_task(autodelete_loop(bot)),
             asyncio.create_task(heartbeat_loop(bot)), asyncio.create_task(server.keep_alive())]
    await enrichment.enqueue_pending()
    await resume_jobs(bot)
    log.info("step 5/5 ready")
    try:
        await idle()
    finally:
        for t in tasks:
            t.cancel()
        await bot.stop()
        await runner.cleanup()


if __name__ == "__main__":
    fail_if_missing()
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
