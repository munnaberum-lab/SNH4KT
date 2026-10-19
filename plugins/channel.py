"""Automatic indexing of new posts in CHANNELS."""
import logging

from pyrogram import Client, filters

import info
from ingest import ingest

log = logging.getLogger("channel")


@Client.on_message(filters.chat(info.CHANNELS) & (filters.video | filters.document | filters.audio))
async def auto_index(client, message):
    result = await ingest(message, "channel")
    log.info("channel %s msg %s -> %s", message.chat.id, message.id, result)
