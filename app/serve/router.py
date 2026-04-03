import re
import time
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session

import app.database
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
    return app.database.SessionLocal()


def _extract_raw_key(authorization):
    """Extract raw API key from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[7:]


async def _resolve_api_key(key_hash, db=None):
    """Resolve API key hash to key data (environment, org, plan). Uses cache first."""
    cached = await get_cached_key(key_hash)
    if cached is not None:
        return cached
    own_db = db is None
    db = db or _db()
    try:
        api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.is_active == True).first()
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key expired")
        env = db.query(Environment).filter(Environment.id == api_key.environment_id).first()
        if not env:
            raise HTTPException(status_code=401, detail="Environment not found")
        project = db.query(Project).filter(Project.id == env.project_id).first()
        if not project:
            raise HTTPException(status_code=401, detail="Project not found")
        org = db.query(Organisation).filter(Organisation.id == project.org_id).first()
        if not org:
            raise HTTPException(status_code=401, detail="Organisation not found")
        key_data = {"environment_id": env.id, "env_name": env.name, "org_id": org.id, "plan": org.plan}
        await cache_key(key_hash, env.id, org.id, org.plan, env.name)
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return key_data
    finally:
        if own_db:
            db.close()


async def _resolve_prompt(env_id, prompt_key):
    """Resolve prompt key to content data. Uses cache first. Returns (data, cache_hit)."""
    cached = await get_cached_prompt(env_id, prompt_key)
    if cached is not None:
        return cached, True
    db = _db()
    try:
        prompt = db.query(Prompt).filter(Prompt.environment_id == env_id, Prompt.key == prompt_key).first()
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found in this environment")
        if not prompt.live_version_id:
            raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' has no approved version yet")
        version = db.query(PromptVersion).filter(
            PromptVersion.id == prompt.live_version_id, PromptVersion.status == "approved"
        ).first()
        if not version:
            raise HTTPException(status_code=404, detail=f"No approved version for '{prompt_key}'")
        content_data = {
            "content": version.content, "version_num": version.version_num,
            "version_id": version.id, "variables": version.variables or {},
        }
        await cache_prompt(env_id, prompt_key, content_data["content"],
                           content_data["version_num"], content_data["version_id"],
                           content_data["variables"])
        return content_data, False
    finally:
        db.close()


def _substitute_variables(content: str, vars_list: list):
    """
    BUG-02 FIX: Replace {{variable}} placeholders.
    Accepts repeated query params: ?vars=name=John&vars=city=London
    Values can contain commas freely. Returns (content, unfilled_list).
    """
    var_dict = {}
    for pair in vars_list:
        if "=" in pair:
            k, v = pair.split("=", 1)
            k = k.strip()
            if re.match(r'^[\w_]+$', k):
                var_dict[k] = v  # preserve value as-is; commas allowed
    for k, v in var_dict.items():
        content = content.replace(f"{{{{{k}}}}}", v)
    unfilled = re.findall(r'\{\{([\w_]+)\}\}', content)
    return content, unfilled


@router.get("/pm/serve/{prompt_key:path}")
async def serve_prompt(
    prompt_key: str,
    request: Request,
    authorization: Optional[str] = Header(None),
    format: str = "text",
    vars: List[str] = Query(default=[]),
):
    t0 = time.monotonic()
    raw_key = _extract_raw_key(authorization)
    key_hash = hash_api_key(raw_key)
    key_data = await _resolve_api_key(key_hash)
    env_id = key_data["environment_id"]
    if settings.serve_rate_limit_rpm > 0:
        allowed, count, limit = await check_rate_limit(key_hash, settings.serve_rate_limit_rpm)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {limit} requests/minute per key"},
                headers={"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0", "Retry-After": "60"}
            )
    content_data, cache_hit = await _resolve_prompt(env_id, prompt_key)
    content, unfilled = _substitute_variables(content_data["content"], vars)
    latency_ms = round((time.monotonic() - t0) * 1000, 2)
    cache_status = "HIT" if cache_hit else "MISS"

    if format == "json":
        resp = {
            "key": prompt_key, "content": content,
            "version": content_data["version_num"],
            "version_id": content_data["version_id"],
            "environment": key_data.get("env_name", ""),
            "variables": content_data["variables"],
            "latency_ms": latency_ms,
            "cache": cache_status,
            "served_at": datetime.now(timezone.utc).isoformat(),
        }
        if unfilled:
            resp["unfilled_variables"] = unfilled
        return resp
    return PlainTextResponse(
        content=content,
        headers={
            "X-PM-Version": str(content_data["version_num"]),
            "X-PM-Latency": str(latency_ms),
            "X-PM-Cache": cache_status,
        }
    )
