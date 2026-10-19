"""Tiny in-memory stand-in for motor, enough for the offline tests."""
import asyncio
import copy
import itertools
import random
import re

_counter = itertools.count(1)


class DuplicateKeyError(Exception):
    pass


class _Res:
    def __init__(self, upserted_id=None, matched=0, modified=0, deleted=0):
        self.upserted_id, self.matched_count, self.modified_count, self.deleted_count = upserted_id, matched, modified, deleted


def _get(doc, path):
    cur = doc
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return _MISSING
    return cur


_MISSING = object()


def _eq(val, cond):
    if isinstance(cond, re.Pattern):
        if isinstance(val, list):
            return any(isinstance(v, str) and cond.search(v) for v in val)
        return isinstance(val, str) and bool(cond.search(val))
    if isinstance(val, list) and not isinstance(cond, list):
        return cond in val
    return val == cond


def _match_cond(val, cond):
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            present = val is not _MISSING
            v = None if not present else val
            if op == "$ne":
                if present and _eq(v, arg):
                    return False
            elif op == "$in":
                if not present or not any(_eq(v, a) for a in arg):
                    return False
            elif op == "$nin":
                if present and any(_eq(v, a) for a in arg):
                    return False
            elif op == "$exists":
                if present != bool(arg):
                    return False
            elif op == "$all":
                if not present or not all(_eq(v, a) for a in arg):
                    return False
            elif op in ("$gt", "$gte", "$lt", "$lte"):
                if not present or v is None:
                    return False
                try:
                    ok = {"$gt": v > arg, "$gte": v >= arg, "$lt": v < arg, "$lte": v <= arg}[op]
                except TypeError:
                    return False
                if not ok:
                    return False
            elif op == "$regex":
                if not present or not _eq(v, re.compile(arg)):
                    return False
            else:
                raise NotImplementedError(op)
        return True
    if val is _MISSING:
        return cond is None
    return _eq(val, cond)


def matches(doc, flt):
    for k, cond in (flt or {}).items():
        if k == "$or":
            if not any(matches(doc, f) for f in cond):
                return False
        elif k == "$and":
            if not all(matches(doc, f) for f in cond):
                return False
        elif not _match_cond(_get(doc, k), cond):
            return False
    return True


def _set(doc, path, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _apply(doc, update, inserting=False):
    for op, fields in update.items():
        if op == "$set":
            for k, v in fields.items():
                _set(doc, k, copy.deepcopy(v))
        elif op == "$setOnInsert":
            if inserting:
                for k, v in fields.items():
                    _set(doc, k, copy.deepcopy(v))
        elif op == "$inc":
            for k, v in fields.items():
                cur = _get(doc, k)
                _set(doc, k, (0 if cur is _MISSING else cur) + v)
        elif op == "$unset":
            for k in fields:
                doc.pop(k, None)
        else:
            raise NotImplementedError(op)


class Cursor:
    def __init__(self, docs):
        self.docs, self._i = docs, 0

    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self.docs.sort(key=lambda x, k=k: (_get(x, k) is _MISSING, _get(x, k) if _get(x, k) is not _MISSING else 0), reverse=(d == -1))
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        if n:
            self.docs = self.docs[:n]
        return self

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return copy.deepcopy(next(self._it))
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in (self.docs[:n] if n else self.docs)]


class Collection:
    def __init__(self):
        self.docs = []

    async def create_index(self, *a, **k):
        return "idx"

    def _find(self, flt):
        return [d for d in self.docs if matches(d, flt)]

    async def find_one(self, flt=None, projection=None):
        await asyncio.sleep(0)  # let other tasks interleave, like a real network call
        for d in self.docs:
            if matches(d, flt):
                return copy.deepcopy(d)
        return None

    def find(self, flt=None, projection=None):
        return Cursor(self._find(flt))

    def aggregate(self, pipeline):
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if matches(d, stage["$match"])]
            elif "$sample" in stage:
                docs = random.sample(docs, min(len(docs), stage["$sample"]["size"]))
        return Cursor(docs)

    async def count_documents(self, flt=None):
        await asyncio.sleep(0)  # let other tasks interleave, like a real network call
        return len(self._find(flt))

    async def insert_one(self, doc):
        await asyncio.sleep(0)  # let other tasks interleave, like a real network call
        doc = copy.deepcopy(doc)
        if "_id" not in doc:
            doc["_id"] = next(_counter)
        if any(d["_id"] == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("dup _id")
        self.docs.append(doc)
        return _Res(upserted_id=doc["_id"])

    async def update_one(self, flt, update, upsert=False):
        await asyncio.sleep(0)  # let other tasks interleave, like a real network call
        for d in self.docs:
            if matches(d, flt):
                _apply(d, update)
                return _Res(matched=1, modified=1)
        if upsert:
            new = {k: copy.deepcopy(v) for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
            _apply(new, update, inserting=True)
            if "_id" not in new:
                new["_id"] = next(_counter)
            self.docs.append(new)
            return _Res(upserted_id=new["_id"])
        return _Res()

    async def update_many(self, flt, update):
        n = 0
        for d in self._find(flt):
            _apply(d, update)
            n += 1
        return _Res(matched=n, modified=n)

    async def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if matches(d, flt):
                del self.docs[i]
                return _Res(deleted=1)
        return _Res()

    async def delete_many(self, flt):
        await asyncio.sleep(0)  # let other tasks interleave, like a real network call
        keep = [d for d in self.docs if not matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep
        return _Res(deleted=n)


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, Collection())

    async def command(self, *a, **k):
        return {"ok": 1}
