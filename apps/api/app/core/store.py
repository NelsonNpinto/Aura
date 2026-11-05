"""Counter/cache store: Upstash Redis over REST in prod, in-memory for tests (§B4, 0.8).

Every multi-key check is ONE Lua EVAL, so a rate-limit or bucket check costs one Upstash command.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

# KEYS = counters; ARGV = [cost_1, limit_1, ttl_1, cost_2, limit_2, ttl_2, ...]
_TAKE_LUA = """
local n = #KEYS
for i = 1, n do
  local cost = tonumber(ARGV[3*i-2])
  local limit = tonumber(ARGV[3*i-1])
  local cur = tonumber(redis.call('GET', KEYS[i]) or '0')
  if cur + cost > limit then
    local ttl = redis.call('TTL', KEYS[i])
    if ttl < 0 then ttl = tonumber(ARGV[3*i]) end
    return {0, i, ttl}
  end
end
for i = 1, n do
  redis.call('INCRBY', KEYS[i], tonumber(ARGV[3*i-2]))
  if redis.call('TTL', KEYS[i]) < 0 then redis.call('EXPIRE', KEYS[i], tonumber(ARGV[3*i])) end
end
return {1, 0, 0}
"""


@dataclass(frozen=True)
class Window:
    key: str
    limit: int
    ttl_s: int
    cost: int = 1


@dataclass(frozen=True)
class TakeResult:
    allowed: bool
    failed_key: str | None = None
    retry_after_s: int = 0


class Store(Protocol):
    async def take(self, windows: list[Window]) -> TakeResult: ...
    async def peek(self, keys: list[str]) -> list[int]: ...
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...
    async def ping(self) -> bool: ...


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = asyncio.Lock()

    def _live(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, exp = item
        if exp is not None and exp <= time.monotonic():
            del self._data[key]
            return None
        return value

    async def take(self, windows: list[Window]) -> TakeResult:
        async with self._lock:
            for w in windows:
                cur = int(self._live(w.key) or 0)
                if cur + w.cost > w.limit:
                    exp = self._data.get(w.key, ("0", None))[1]
                    ttl = int(exp - time.monotonic()) + 1 if exp else w.ttl_s
                    return TakeResult(False, w.key, max(ttl, 1))
            for w in windows:
                cur = int(self._live(w.key) or 0)
                exp = self._data.get(w.key, ("0", None))[1] if cur else None
                self._data[w.key] = (str(cur + w.cost), exp or time.monotonic() + w.ttl_s)
            return TakeResult(True)

    async def peek(self, keys: list[str]) -> list[int]:
        return [int(self._live(k) or 0) for k in keys]

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl_s)

    async def ping(self) -> bool:
        return True


class UpstashStore:
    def __init__(self, url: str, token: str) -> None:
        from upstash_redis.asyncio import Redis

        self._r = Redis(url=url, token=token)

    async def take(self, windows: list[Window]) -> TakeResult:
        args: list[str] = []
        for w in windows:
            args += [str(w.cost), str(w.limit), str(w.ttl_s)]
        res = await self._r.eval(_TAKE_LUA, keys=[w.key for w in windows], args=args)
        ok, idx, ttl = (int(x) for x in res)
        if ok:
            return TakeResult(True)
        return TakeResult(False, windows[idx - 1].key, max(ttl, 1))

    async def peek(self, keys: list[str]) -> list[int]:
        if not keys:
            return []
        vals = await self._r.mget(*keys)
        return [int(v or 0) for v in vals]

    async def get(self, key: str) -> str | None:
        v = await self._r.get(key)
        return None if v is None else str(v)

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._r.set(key, value, ex=ttl_s)

    async def ping(self) -> bool:
        return bool(await self._r.ping())


@lru_cache
def get_store() -> Store:
    s = get_settings()
    if s.upstash_redis_rest_url and s.upstash_redis_rest_token:
        return UpstashStore(s.upstash_redis_rest_url, s.upstash_redis_rest_token.get_secret_value())
    if s.is_deployed:
        raise RuntimeError("UPSTASH_REDIS_REST_URL/TOKEN required outside local/test")
    return MemoryStore()


def minute_bucket(now: float | None = None) -> str:
    return str(int((now or time.time()) // 60))


def day_bucket(now: float | None = None) -> str:
    return time.strftime("%Y%m%d", time.gmtime(now or time.time()))


def seconds_to_utc_midnight(now: float | None = None) -> int:
    t = now or time.time()
    return int(86400 - (t % 86400))
