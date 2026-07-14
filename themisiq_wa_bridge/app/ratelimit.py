"""In-memory rate limiter.

Simple fixed-window limiter keyed by wa_user_id. Good enough for a single
instance MVP; swap for Redis-backed if you scale horizontally.
"""
from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, limit_per_window: int, window_seconds: int = 60):
        self.limit = limit_per_window
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = __import__("threading").Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            # drop expired
            self._hits[key] = [t for t in hits if now - t < self.window]
            if len(self._hits[key]) >= self.limit:
                return False
            self._hits[key].append(now)
            return True
