"""Token bucket rate limiter for API calls."""

from __future__ import annotations

import time
import threading


class RateLimiter:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate: float, per: float = 1.0):
        """
        Args:
            rate: Number of tokens (requests) allowed per interval.
            per: Interval in seconds (default 1.0).
        """
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
        self.last_refill = now

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
            time.sleep(0.05)


# Shared limiters
arxiv_limiter = RateLimiter(rate=1, per=3.0)       # 1 request per 3 seconds
s2_limiter = RateLimiter(rate=10, per=1.0)          # 10 requests per second
web_limiter = RateLimiter(rate=1, per=2.0)          # Polite crawling: 1 req per 2 sec
openreview_limiter = RateLimiter(rate=2, per=1.0)   # Conservative: 2 req per second
