"""
Serve Router — GET /pm/serve/{key}
====================================
The ONLY endpoint agents call at runtime.
Optimised for latency and availability.

Flow:
  1. Extract API key from Authorization header
  2. Hash + cache lookup (Upstash Redis Level 1)
  3. Cache miss → Supabase query → cache
  4. Rate limit check (Upstash sliding window counter, per API key)
  5. Prompt cache lookup (Upstash Redis Level 2)
  6. Cache miss → Supabase query → cache
  7. Variable substitution if ?vars= provided
  8. Return plain text or JSON

Latency targets (with Upstash):
  Cache hit:  ~20-40ms
  DB read:    ~80-150ms
"""

import time
import datetime as dt
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.serve.cache import (
    get_cached_key, cache_key,
    get_cached_prompt, cache_prompt,
    invalidate_prompt_cache,
    check_rate_limit,
)
from app.core.auth import hash_api_key
from app.models import ApiKey, Environment, Prompt, PromptVersion, Organisation, Project
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def _db() -> Session:
    return SessionLocal()


@router.get("/pm/serve/{prompt_key:path}")
async def serve_prompt(
    prompt_key: str,
    request: Request,
    authorization: Optional[str] = Header(None),
    format: str = "text",
    vars: Optional[str] = None,
):
    """
    Runtime endpoint. Called by agents, n8n, LangChain, curl — anything.

    Headers:
      Authorization: Bearer pm_live_xxxxxxxx

    Returns plain text by default. Add ?format=json for metadata.
    Variable substitution: ?vars=tone=formal,name=Acme
    """
    t_start = time.monotonic()

    # ── 1. Extract API key ───────────────────────────────────────
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    raw_key = authorization[7:]
    key_hash = hash_api_key(raw_key)

    # ── 2. Key cache lookup ──────────────────────────────────────
    key_data = await get_cached_key(key_hash)

    if key_data is None:
        db = _db()
        try:
            api_key_row = db.query(ApiKey).filter(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True
            ).first()

            if not api_key_row:
                raise HTTPException(status_code=401, detail="Invalid API key")

            if api_key_row.expires_at and api_key_row.expires_at < dt.datetime.utcnow():
                raise HTTPException(status_code=401, detail="API key expired")

            env = db.query(Environment).filter(
                Environment.id == api_key_row.environment_id
            ).first()
            if not env:
                raise HTTPException(status_code=401, detail="Environment not found")

            project = db.query(Project).filter(Project.id == env.project_id).first()
            if not project:
                raise HTTPException(status_code=401, detail="Project not found")

            org = db.query(Organisation).filter(Organisation.id == project.org_id).first()
            if not org:
                raise HTTPException(status_code=401, detail="Organisation not found")

            key_data = {
                "environment_id": env.id,
                "env_name": env.name,
                "org_id": org.id,
                "plan": org.plan,
            }
            await cache_key(key_hash, env.id, org.id, org.plan, env.name)

            api_key_row.last_used_at = dt.datetime.utcnow()
            db.commit()
        finally:
            db.close()

    environment_id = key_data["environment_id"]

    # ── 3. Rate limit check ──────────────────────────────────────
    # Sliding window counter keyed per API key hash.
    # Uses Upstash INCR — works across all Vercel function instances.
    # Fails open on any Redis error to never block legitimate traffic.
    if settings.serve_rate_limit_rpm > 0:
        allowed, count, limit = await check_rate_limit(
            key_hash, settings.serve_rate_limit_rpm
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {limit} requests/minute per key"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60",
                }
            )

    # ── 4. Prompt cache lookup ───────────────────────────────────
    cached = await get_cached_prompt(environment_id, prompt_key)

    if cached is None:
        db = _db()
        try:
            prompt_row = db.query(Prompt).filter(
                Prompt.environment_id == environment_id,
                Prompt.key == prompt_key
            ).first()

            if not prompt_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Prompt '{prompt_key}' not found in this environment"
                )
            if not prompt_row.live_version_id:
                raise HTTPException(
                    status_code=404,
                    detail=f"Prompt '{prompt_key}' has no approved version yet"
                )

            version_row = db.query(PromptVersion).filter(
                PromptVersion.id == prompt_row.live_version_id,
                PromptVersion.status == "approved"
            ).first()

            if not version_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"No approved version for '{prompt_key}'"
                )

            cached = {
                "content": version_row.content,
                "version_num": version_row.version_num,
                "version_id": version_row.id,
                "variables": version_row.variables or {},
            }
            await cache_prompt(
                environment_id, prompt_key,
                cached["content"], cached["version_num"],
                cached["version_id"], cached["variables"]
            )
        finally:
            db.close()

    content = cached["content"]

    # ── 5. Variable substitution ─────────────────────────────────
    if vars:
        for pair in vars.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                content = content.replace(f"{{{{{k.strip()}}}}}", v.strip())

    # ── 6. Return ────────────────────────────────────────────────
    latency_ms = round((time.monotonic() - t_start) * 1000, 2)

    if format == "json":
        return {
            "key": prompt_key,
            "content": content,
            "version": cached["version_num"],
            "version_id": cached["version_id"],
            "environment": key_data.get("env_name", ""),
            "variables": cached["variables"],
            "latency_ms": latency_ms,
            "served_at": dt.datetime.utcnow().isoformat() + "Z",
        }

    return PlainTextResponse(
        content=content,
        headers={
            "X-PM-Version": str(cached["version_num"]),
            "X-PM-Latency": str(latency_ms),
        }
    )
