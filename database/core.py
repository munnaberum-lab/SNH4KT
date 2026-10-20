"""MongoDB connection (motor) and index creation. Tests call use() with a fake database."""
import logging

import info

log = logging.getLogger("db")


class Store:
    other = None        # database for users, groups, settings, etc.
    file_dbs = []       # databases holding the files collection (first = preferred)

    def col(self, name):
        return self.other[name]

    @property
    def files_cols(self):
        return [d[info.COLLECTION_NAME] for d in self.file_dbs]


store = Store()


def use(other, file_dbs=None):
    """Plug in databases (used by tests and by init)."""
    store.other = other
    store.file_dbs = file_dbs or [other]


def col(name):
    return store.other[name]


def files_cols():
    return store.files_cols


async def init():
    from motor.motor_asyncio import AsyncIOMotorClient
    uris = {"other": info.DATABASE_URI, "files": [info.DATABASE_URI]}
    if info.MULTIPLE_DATABASE:
        uris["other"] = info.O_DB_URI or info.DATABASE_URI
        uris["files"] = [u for u in dict.fromkeys([info.F_DB_URI, info.S_DB_URI, info.DATABASE_URI]) if u]
    clients = {}

    def db_for(uri):
        if uri not in clients:
            clients[uri] = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=15000)
        return clients[uri][info.DATABASE_NAME]

    use(db_for(uris["other"]), [db_for(u) for u in uris["files"]])
    await store.other.command("ping")
    await create_indexes()
    log.info("MongoDB connected (%d file database(s))", len(store.file_dbs))


async def create_indexes():
    for c in store.files_cols:
        await c.create_index("tokens")
        await c.create_index("sid", unique=True, sparse=True)
        await c.create_index([("kind", 1), ("hidden", 1), ("added", -1)])
        await c.create_index([("kind", 1), ("hidden", 1), ("views", -1)])
        await c.create_index("quality")
        await c.create_index("year")
        await c.create_index("bin", sparse=True)
        await c.create_index([("name", 1), ("size", 1)])
    o = col
    await o("autodelete").create_index("at")
    await o("verify").create_index("expires", expireAfterSeconds=0)
    await o("verified").create_index("expires", expireAfterSeconds=0)
    await o("referrals").create_index([("owner", 1), ("joined_user", 1)], unique=True)
    await o("join_reqs").create_index([("uid", 1), ("chan", 1)])
    await o("filters").create_index([("group", 1), ("text", 1)])
    await o("requests").create_index("uid")
    await o("accounts").create_index("aid", unique=True)
    await o("likes").create_index([("uid", 1), ("sid", 1)], unique=True)
    await o("likes").create_index([("uid", 1), ("at", -1)])
    await o("playlists").create_index("uid")
    await o("login_tokens").create_index("expires", expireAfterSeconds=0)
    await o("admin_otp").create_index("expires", expireAfterSeconds=0)
    await o("quota").create_index("expires", expireAfterSeconds=0)
    await o("audit").create_index([("at", -1)])
    for c in store.files_cols:
        await c.create_index("tags")
