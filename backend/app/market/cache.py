"""A small TTL cache for market data.

WHY THIS IS NOT OPTIONAL
------------------------
While building this project we hit CoinGecko's free-tier rate limit (HTTP
429) after only nine requests in quick succession. Without caching, a
handful of users refreshing the dashboard would exhaust the quota within
seconds and the application would simply stop showing prices.

STALE-WHILE-ERROR
-----------------
The cache keeps entries past their TTL rather than deleting them. If a
refresh fails, we can serve the expired value -- but ONLY flagged as stale,
so the interface can say "price from 2 minutes ago" instead of presenting
it as current.

That flag is the whole point. Silently serving an old price as if it were
live is exactly the kind of dishonesty this project is built to avoid.
"""

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    stored_at: float
    ttl_seconds: float

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.stored_at

    @property
    def is_fresh(self) -> bool:
        return self.age_seconds < self.ttl_seconds


class TtlCache(Generic[T]):
    """In-process cache keyed by string.

    In-process is a deliberate choice for this stage: one backend process,
    no extra infrastructure. Moving to Redis later means replacing this
    class, and nothing that uses it.
    """

    def __init__(self, default_ttl_seconds: float = 60.0) -> None:
        self._entries: dict[str, CacheEntry[T]] = {}
        self._default_ttl = default_ttl_seconds

    def get_fresh(self, key: str) -> T | None:
        """Value if present and within its TTL, otherwise None."""
        entry = self._entries.get(key)
        if entry is None or not entry.is_fresh:
            return None
        return entry.value

    def get_stale(self, key: str) -> tuple[T, float] | None:
        """Expired value plus its age, for use when a refresh has failed.

        Returns None if nothing was ever cached under this key.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        return entry.value, entry.age_seconds

    def set(self, key: str, value: T, ttl_seconds: float | None = None) -> None:
        self._entries[key] = CacheEntry(
            value=value,
            stored_at=time.monotonic(),
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self._default_ttl,
        )

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
