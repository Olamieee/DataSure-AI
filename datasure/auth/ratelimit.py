"""In-process sliding-window rate limiting for login attempts.

Counts failures per username and per remote address. When more than
`max_attempts` failures occur within `window_seconds`, the key is blocked
for `block_seconds`. Successful login resets both counters for that user.

Scope note: counters live in the web process's memory. With multiple
worker processes each one limits independently; a Redis-backed store is
a documented upgrade path for clustered deployments.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """Fixed-parameter sliding window limiter, thread-safe."""

    def __init__(self, max_attempts: int, window_seconds: int, block_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_blocked(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Returns (blocked, remaining_seconds)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            until = self._blocked_until.get(key)
            if until is not None:
                if now < until:
                    return True, int(until - now) + 1
                del self._blocked_until[key]
            return False, 0

    def record_failure(self, key: str, now: float | None = None) -> int:
        """Register one failure; returns the penalty applied (0 = none)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._attempts[key]
            attempts.append(now)
            cutoff = now - self.window_seconds
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            if len(attempts) >= self.max_attempts:
                self._blocked_until[key] = now + self.block_seconds
                attempts.clear()
                return self.block_seconds
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
            self._blocked_until.pop(key, None)

    def reset_all(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._blocked_until.clear()


login_limiter = SlidingWindowLimiter(
    max_attempts=5, window_seconds=600, block_seconds=900
)


def user_key(username: str) -> str:
    return f"user:{username.strip().lower()}"


def address_key(address: str) -> str:
    return f"ip:{address or 'unknown'}"
