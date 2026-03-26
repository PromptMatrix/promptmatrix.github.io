import json
import logging
from typing import Optional
from app.config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)

class _UpstashCache:
    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._token = token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def get(self, key: str) -> Optional[str]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(
                    f"{self._url}/get/{key}",
                    headers=self._headers()
                )
                data = r.json()
                return data.get("result")
        except Exception as e:
            log.debug(f"Cache GET error: {e}")
            return None

    async def set(self, key: str, value: str, ttl_seconds: int):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(
                    f"{self._url}/set/{key}/{value}",
                    params={"ex": ttl_seconds},
                    headers=self._headers()
                )
        except Exception as e:
            log.debug(f"Cache SET error: {e}")

    async def delete(self, key: str):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(
                    f"{self._url}/del/{key}",
                    headers=self._headers()
                )
        except Exception as e:
            log.debug(f"Cache DEL error: {e}")

class _MemoryCache:
    def __init__(self):
        self._data = {} # key -> (value, expiry_ts)

    def _now(self):
        import time
        return time.time()

    async def get(self, key: str) -> Optional[str]:
        item = self._data.get(key)
        if not item:
            return None
        val, expiry = item
        if expiry and self._now() > expiry:
            del self._data[key]
            return None
        return val

    async def set(self, key: str, value: str, ttl_seconds: int):
        expiry = self._now() + ttl_seconds if ttl_seconds > 0 else 0
        self._data[key] = (value, expiry)

    async def delete(self, key: str):
        if key in self._data:
            del self._data[key]

    async def incr(self, key: str, ttl_seconds: int) -> int:
        item = self._data.get(key)
        now = self._now()
        if not item or (item[1] and now > item[1]):
            val = 1
        else:
            val = int(item[0]) + 1
        expiry = now + ttl_seconds if not item or (item[1] and now > item[1]) else item[1]
        self._data[key] = (str(val), expiry)
        return val

def _build_cache():
    if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token:
        log.info("Cache: Upstash Redis enabled")
        return _UpstashCache(
            settings.upstash_redis_rest_url,
            settings.upstash_redis_rest_token
        )
    log.info("Cache: Local memory cache enabled (Local-First)")
    return _MemoryCache()

_cache = _build_cache()

async def get_cached_key(key_hash: str) -> Optional[dict]:
    raw = await _cache.get(f"key:{key_hash}")
    return json.loads(raw) if raw else None

async def cache_key(key_hash: str, environment_id: str, org_id: str, plan: str, env_name: str):
    await _cache.set(
        f"key:{key_hash}",
        json.dumps({"environment_id": environment_id, "org_id": org_id, "plan": plan, "env_name": env_name}),
        settings.api_key_cache_ttl_seconds
    )

async def invalidate_key_cache(key_hash: str):
    await _cache.delete(f"key:{key_hash}")

async def get_cached_prompt(environment_id: str, prompt_key: str) -> Optional[dict]:
    raw = await _cache.get(f"prompt:{environment_id}:{prompt_key}")
    return json.loads(raw) if raw else None

async def cache_prompt(
    environment_id: str, prompt_key: str,
    content: str, version_num: int, version_id: str, variables: dict
):
    await _cache.set(
        f"prompt:{environment_id}:{prompt_key}",
        json.dumps({
            "content": content,
            "version_num": version_num,
            "version_id": version_id,
            "variables": variables,
        }),
        settings.prompt_cache_ttl_seconds
    )

async def invalidate_prompt_cache(environment_id: str, prompt_key: str):
    await _cache.delete(f"prompt:{environment_id}:{prompt_key}")

async def check_rate_limit(key_hash: str, rpm_limit: int = 600) -> tuple[bool, int, int]:
    if rpm_limit == 0:
        return True, 0, 0
    import time
    window = int(time.time() // 60)
    rate_key = f"rl:{key_hash}:{window}"
    
    if isinstance(_cache, _MemoryCache):
        count = await _cache.incr(rate_key, 120)
        return count <= rpm_limit, count, rpm_limit
        
    try:
        import httpx
        headers = _cache._headers()
        base_url = _cache._url
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(f"{base_url}/incr/{rate_key}", headers=headers)
            count = int(r.json().get("result", 1))
            if count == 1:
                await client.get(
                    f"{base_url}/expire/{rate_key}/120",
                    headers=headers
                )
        allowed = count <= rpm_limit
        return allowed, count, rpm_limit
    except Exception as e:
        log.debug(f"Rate limit check error: {e}")
        return True, 0, rpm_limit
