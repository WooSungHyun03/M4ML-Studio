"""Per-client request limits (sliding window, in memory).

Best effort against floods from one address; the authoritative protections are the
session/slot/GPU/disk limits in the database. A restart forgets the windows on purpose.
"""

from __future__ import annotations

import time
from collections import deque

# bucket -> (requests, seconds)
LIMITS = {
    "api": (600, 60),       # everything under /api
    "frame": (6000, 60),    # live-render frames (100/s)
    "upload": (120, 60),    # photo uploads (one photo per request)
    "recover": (10, 3600),  # recovery link attempts
    "session": (20, 3600),  # session open attempts (new sessions are limited separately)
}
MAX_CLIENTS = 10000


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, int]] | None = None):
        self.limits = dict(LIMITS if limits is None else limits)
        self._hits: dict[tuple[str, str], deque] = {}

    def allow(self, client: str, bucket: str, now: float | None = None) -> bool:
        count, window = self.limits[bucket]
        now = time.monotonic() if now is None else now
        if len(self._hits) > MAX_CLIENTS:  # bounded memory under a flood of addresses
            self._hits.clear()
        hits = self._hits.setdefault((client, bucket), deque())
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= count:
            return False
        hits.append(now)
        return True
