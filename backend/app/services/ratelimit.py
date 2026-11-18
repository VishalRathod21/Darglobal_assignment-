"""In-memory sliding-window rate limiter, keyed by client IP.

Protects the shared free-tier LLM quota from one noisy client. In-memory is correct for a
single instance; with several replicas the counters would move to Redis.
"""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, seconds_until_retry)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            if len(self._hits) > 5000:  # bound memory under many distinct clients
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[stale]
            return True, 0
