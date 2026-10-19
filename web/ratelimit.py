"""Sliding-window rate limiter (in memory)."""
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self._hits = defaultdict(deque)

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > 20000:  # keep memory bounded
            for k in [k for k, v in self._hits.items() if not v][:5000]:
                self._hits.pop(k, None)
        return True

    def reset(self, key):
        self._hits.pop(key, None)

    def peek(self, key, now=None):
        """How many hits are inside the window (without recording one)."""
        now = time.monotonic() if now is None else now
        q = self._hits.get(key) or ()
        return sum(1 for t in q if t > now - self.window)
