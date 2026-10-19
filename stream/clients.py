"""Main bot plus extra bot tokens for load sharing."""
import asyncio
import logging

import info
import state

log = logging.getLogger("clients")


async def start_extra_clients():
    """Each MULTI_TOKEN<n> bot starts with no_updates and in_memory. Failures only log a warning."""
    from pyrogram import Client
    state.clients.setdefault(0, state.main)
    state.work_loads.setdefault(0, 0)

    async def start(i, token):
        try:
            c = Client(name=f"extra_{i}", api_id=info.API_ID, api_hash=info.API_HASH, bot_token=token,
                       no_updates=True, in_memory=True, sleep_threshold=info.SLEEP_THRESHOLD)
            await c.start()
            state.clients[i] = c
            state.work_loads[i] = 0
            log.info("extra client %s started", i)
        except Exception as e:  # noqa
            log.warning("extra client %s failed to start: %s", i, e)

    await asyncio.gather(*[start(i, t) for i, t in enumerate(info.MULTI_TOKENS, start=1)])


def pick_client():
    """Least busy client. Returns (client_id, client)."""
    if not state.clients:
        state.clients[0] = state.main
        state.work_loads[0] = 0
    cid = min(state.work_loads, key=state.work_loads.get)
    return cid, state.clients[cid]


def active_streams():
    return sum(state.work_loads.values())
