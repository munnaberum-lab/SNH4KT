"""Shared runtime state (no imports from the rest of the app, so no cycles)."""
import time

started_at = time.time()
bot_username = ""
clients = {}       # client_id -> pyrogram Client (0 is the main bot)
work_loads = {}    # client_id -> active streams
main = None        # the main bot client, set by bot.py
