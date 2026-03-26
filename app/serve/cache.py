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

class _NoopCache:
    async def get(self, key: str) -> Optional[str]:
        return None
    async def set(self, key: str, value: str, ttl_seconds: int):
        pass
    async def delete(self, key: str):
        pass

def _build_cache():
    if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token:
        log.info("Cache: Upstash Redis enabled")
        return _UpstashCache(
            settings.upstash_redis_rest_url,
            settings.upstash_redis_rest_token
        )
    log.info("Cache: disabled")
    return _NoopCache()

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
    if isinstance(_cache, _NoopCache):
        return True, 0, rpm_limit
    import time
    window = int(time.time() // 60)
    rate_key = f"rl:{key_hash}:{window}"
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
