from __future__ import annotations

import asyncio
import time
from collections import OrderedDict


class TTLCache:
    """Минимальный TTL-кеш для антифлуда и одноразовых блокировок."""

    def __init__(self, ttl: float, max_size: int = 10_000) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._data: OrderedDict[str, float] = OrderedDict()

    def _evict(self, now: float) -> None:
        while self._data:
            key, expires = next(iter(self._data.items()))
            if expires > now and len(self._data) <= self.max_size:
                break
            self._data.pop(key, None)

    def hit(self, key: str) -> bool:
        """True если ключ уже был активен (значит — флуд)."""
        now = time.monotonic()
        self._evict(now)
        expires = self._data.get(key)
        if expires and expires > now:
            return True
        self._data[key] = now + self.ttl
        self._data.move_to_end(key)
        return False


class RateLimiter:
    """Простой ограничитель частоты для рассылок (N сообщений в секунду)."""

    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_for = self._next_at - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                now = time.monotonic()
            self._next_at = now + self._interval


class NamedLocks:
    """Именованные asyncio-локи: не даём двум задачам работать по одному ключу."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, name: str) -> asyncio.Lock:
        lock = self._locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[name] = lock
        return lock


named_locks = NamedLocks()
