"""
Serve Cache
===========
Uses Upstash Redis (HTTP-based, works on Vercel serverless).
Falls back to no-op cache if UPSTASH_REDIS_REST_URL is not set.

Why Upstash and not an in-memory dict?
  Vercel creates a new process instance per request (and runs multiple
  instances in parallel). A Python dict cache is destroyed after each
  invocation — it never warms up. Upstash is an external key-value store
  accessed via HTTP, so all Vercel instances share the same cache.

Free tier: 10,000 commands/day — enough for ~5,000 serve requests/day
(each request = 1 GET for the API key + 1 GET for the prompt).
Upgrade to paid Upstash ($0.20/100k commands) when you exceed that.

If Upstash is not configured:
  Every serve request reads directly from Supabase (Postgres).
  Latency: ~80-150ms instead of ~20-40ms.
  Correct for development and early beta. Not a correctness issue.
"""

import json
import logging
from typing import Optional
from app.config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)


class _UpstashCache:
    """Upstash Redis via REST API. No persistent connection — safe for serverless."""

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
    """Used when Upstash is not configured. Always returns cache miss."""
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
    log.info("Cache: disabled (no Upstash credentials) — direct DB reads")
    return _NoopCache()


_cache = _build_cache()


# ── API Key Cache ────────────────────────────────────────────────

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


# ── Prompt Cache ─────────────────────────────────────────────────

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
    """Called immediately when a version is approved."""
    await _cache.delete(f"prompt:{environment_id}:{prompt_key}")


# ── Rate Limiting ─────────────────────────────────────────────────
# Sliding window counter using Upstash INCR + EXPIRE.
# Keyed per API key hash so limits are per-integration, not per-IP.
# Falls back to allow-all if Upstash is not configured (same as cache).
#
# Default: 600 requests/minute per key (~10 req/sec).
# Set SERVE_RATE_LIMIT_RPM in env to override. Set to 0 to disable.

async def check_rate_limit(key_hash: str, rpm_limit: int = 600) -> tuple[bool, int, int]:
    """
    Sliding window rate limit check.

    Returns: (allowed, current_count, limit)
      allowed=True  → request proceeds
      allowed=False → return 429 to caller

    Uses a 60-second window keyed by minute boundary so counters
    reset cleanly. Two sequential GET/INCR calls kept deliberately
    simple to minimise Upstash command spend on the free tier.
    """
    if rpm_limit == 0:
        return True, 0, 0

    if isinstance(_cache, _NoopCache):
        # No Upstash configured — rate limiting disabled, allow all
        return True, 0, rpm_limit

    import time
    window = int(time.time() // 60)   # current 60-second bucket
    rate_key = f"rl:{key_hash}:{window}"

    try:
        import httpx
        headers = _cache._headers()  # type: ignore[union-attr]
        base_url = _cache._url       # type: ignore[union-attr]

        async with httpx.AsyncClient(timeout=1.0) as client:
            # INCR — atomically increment counter, returns new value
            r = await client.get(f"{base_url}/incr/{rate_key}", headers=headers)
            count = int(r.json().get("result", 1))

            # Set expiry on first request in window only (count == 1)
            # Saves one round-trip on all subsequent requests
            if count == 1:
                await client.get(
                    f"{base_url}/expire/{rate_key}/120",  # 2x window = safe margin
                    headers=headers
                )

        allowed = count <= rpm_limit
        return allowed, count, rpm_limit

    except Exception as e:
        log.debug(f"Rate limit check error (allowing): {e}")
        # On any Redis error, fail open — never block legitimate traffic
        return True, 0, rpm_limit
