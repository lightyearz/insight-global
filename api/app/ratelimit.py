"""Tiny in-process token bucket (POC abuse limit; the app is single-process by design)."""

from __future__ import annotations

import time


class TokenBucket:
    """``rate_per_minute`` tokens refill continuously up to ``burst``; one token per call."""

    def __init__(self, rate_per_minute: float, burst: int) -> None:
        self.rate = max(rate_per_minute, 0.0) / 60.0
        self.burst = max(1, burst)
        self._buckets: dict[str, tuple[float, float]] = {}

    def take(self, key: str, now: float | None = None) -> float:
        """Consume a token for ``key``. Returns 0 if allowed, else seconds until the next token."""
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(key, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + (now - last) * self.rate)
        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return 0.0
        self._buckets[key] = (tokens, now)
        return (1 - tokens) / self.rate if self.rate > 0 else 60.0
