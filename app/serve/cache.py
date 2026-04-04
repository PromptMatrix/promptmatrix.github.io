"""
Local-only in-memory cache.
No external dependencies. No Redis. No Upstash. No network calls.
"""

import logging
import time
from typing import Optional

from app.config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)


class _MemoryCache:
    """Pure Python in-process TTL cache. Zero external deps."""

    MAX_ENTRIES = 5000  # Increased for larger deployments

    def __init__(self):
        self._data: dict = {}  # key -> (value: Any, expiry_ts: float)

    def _now(self) -> float:
        return time.time()

    async def get(self, key: str):
        item = self._data.get(key)
        if not item:
            return None
        val, expiry = item
        if expiry and self._now() > expiry:
            del self._data[key]
            return None
        return val

    async def set(self, key: str, value, ttl_seconds: int):
        if len(self._data) >= self.MAX_ENTRIES:
            # FIFO eviction: remove oldest entry
            oldest = next(iter(self._data))
            del self._data[oldest]
        expiry = self._now() + ttl_seconds if ttl_seconds > 0 else 0
        self._data[key] = (value, expiry)

    async def delete(self, key: str):
        self._data.pop(key, None)

    async def incr(self, key: str, ttl_seconds: int) -> int:
        item = self._data.get(key)
        now = self._now()
        if not item or (item[1] and now > item[1]):
            val = 1
            expiry = now + ttl_seconds
        else:
            val = int(item[0]) + 1
            expiry = item[1]
        self._data[key] = (val, expiry)
        return val


# Singleton
_cache = _MemoryCache()


class _NoopCache:
    """No-op cache for tests or when caching is explicitly disabled.\n    All operations succeed silently — reads always miss, writes are dropped."""

    async def get(self, key: str):
        return None

    async def set(self, key: str, value, ttl_seconds: int):
        pass

    async def delete(self, key: str):
        pass

    async def incr(self, key: str, ttl_seconds: int) -> int:
        return 1  # Always first request — rate limiting disabled


# ── Public API (Object-based, No JSON overhead) ───────────────────────────


async def get_cached_key(key_hash: str) -> Optional[dict]:
    return await _cache.get(f"key:{key_hash}")


async def cache_key(
    key_hash: str,
    environment_id: str,
    org_id: str,
    plan: str,
    env_name: str,
    api_key_id: str,
):
    await _cache.set(
        f"key:{key_hash}",
        {
            "api_key_id": api_key_id,
            "environment_id": environment_id,
            "org_id": org_id,
            "plan": plan,
            "env_name": env_name,
        },
        settings.api_key_cache_ttl_seconds,
    )


async def invalidate_key_cache(key_hash: str):
    await _cache.delete(f"key:{key_hash}")


async def get_cached_prompt(environment_id: str, prompt_key: str) -> Optional[dict]:
    return await _cache.get(f"prompt:{environment_id}:{prompt_key}")


async def cache_prompt(
    environment_id: str,
    prompt_key: str,
    content: str,
    version_num: int,
    version_id: str,
    variables: dict,
    prompt_id: str,
):
    await _cache.set(
        f"prompt:{environment_id}:{prompt_key}",
        {
            "prompt_id": prompt_id,
            "content": content,
            "version_num": version_num,
            "version_id": version_id,
            "variables": variables,
        },
        settings.prompt_cache_ttl_seconds,
    )


async def invalidate_prompt_cache(environment_id: str, prompt_key: str):
    await _cache.delete(f"prompt:{environment_id}:{prompt_key}")


async def check_rate_limit(
    key_hash: str, rpm_limit: int = 600
) -> tuple[bool, int, int]:
    if rpm_limit == 0:
        return True, 0, 0
    window = int(time.time() // 60)
    rate_key = f"rl:{key_hash}:{window}"
    count = await _cache.incr(rate_key, 120)
    return count <= rpm_limit, count, rpm_limit
