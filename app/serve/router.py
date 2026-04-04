import re
import time
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException, Header, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session

import app.database
from app.serve.cache import (
    get_cached_key, cache_key,
    get_cached_prompt, cache_prompt,
    check_rate_limit,
)
from app.core.auth import hash_api_key
from app.models import ApiKey, Environment, Prompt, PromptVersion, Organisation, Project, ServeEvent
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
    """Resolve API key hash with object-based caching."""
    cached = await get_cached_key(key_hash)
    if cached:
        return cached
    
    own_db = db is None
    db = db or _db()
    try:
        api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.is_active).first()
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        env = db.query(Environment).filter(Environment.id == api_key.environment_id).first()
        project = db.query(Project).filter(Project.id == env.project_id).first()
        org = db.query(Organisation).filter(Organisation.id == project.org_id).first()
        
        key_data = {
            "api_key_id": api_key.id,
            "environment_id": env.id, 
            "env_name": env.name, 
            "org_id": org.id, 
            "plan": org.plan
        }
        await cache_key(key_hash, env.id, org.id, org.plan, env.name, api_key_id=api_key.id)
        return key_data
    finally:
        if own_db:
            db.close()


async def _resolve_prompt(env_id, prompt_key):
    """Resolve prompt with object-based caching."""
    cached = await get_cached_prompt(env_id, prompt_key)
    if cached:
        return cached, True
    
    db = _db()
    try:
        prompt = db.query(Prompt).filter(Prompt.environment_id == env_id, Prompt.key == prompt_key).first()
        if not prompt or not prompt.live_version_id:
            raise HTTPException(status_code=404, detail="Prompt not found or has no live version")
        
        version = db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
        content_data = {
            "prompt_id": prompt.id,
            "content": version.content,
            "version_num": version.version_num,
            "version_id": version.id,
            "variables": version.variables or {},
        }
        await cache_prompt(env_id, prompt_key, **content_data)
        return content_data, False
    finally:
        db.close()


def _substitute_variables(content: str, vars_list: list, query_params: dict):
    """
    Optimized substitution using direct string replacement.
    Supports both ?vars=k=v and direct ?k=v mapping.
    """
    var_dict = {}
    
    # 1. Process explicit vars list (k=v)
    for pair in vars_list:
        if "=" in pair:
            k, v = pair.split("=", 1)
            var_dict[k.strip()] = v
    
    # 2. Process direct query params (for non-reserved keys)
    reserved = {"vars", "format", "api_key", "version"}
    for k, v in query_params.items():
        if k not in reserved:
            var_dict[k] = v
            
    # 3. Perform substitutions
    for k, v in var_dict.items():
        content = content.replace(f"{{{{{k}}}}}", str(v))
        
    unfilled = re.findall(r'\{\{([\w_]+)\}\}', content)
    return content, unfilled


def _log_serve_event_bg(
    org_id: str,
    api_key_id: str,
    prompt_id: str,
    version_id: str,
    environment_id: str,
    latency_ms: int,
    outcome: str = "served",
    extra: dict = None
):
    """Background task to log telemetry to SQLite."""
    db = _db()
    try:
        event = ServeEvent(
            org_id=org_id,
            api_key_id=api_key_id,
            prompt_id=prompt_id,
            version_id=version_id,
            environment_id=environment_id,
            latency_ms=latency_ms,
            outcome=outcome,
            extra=extra or {}
        )
        db.add(event)
        db.commit()
    except Exception:
        # Prevent telemetry failures from affecting usage
        pass
    finally:
        db.close()


@router.get("/pm/serve/{prompt_key:path}")
async def serve_prompt(
    prompt_key: str,
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
    format: str = "text",
    vars: List[str] = Query(default=[]),
):
    t0 = time.monotonic()
    
    # 🔒 DEV BYPASS: Strictly localhost only, never in production
    if not authorization and settings.app_env == "development":
        client_host = request.client.host if request.client else None
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=401, detail="Authorization required")
            
        db = _db()
        try:
            env = db.query(Environment).filter(Environment.name == "development").first() or db.query(Environment).first()
            project = db.query(Project).filter(Project.id == env.project_id).first()
            org = db.query(Organisation).filter(Organisation.id == project.org_id).first()
            # Note: For dev bypass, we use a placeholder for api_key_id
            key_data = {
                "api_key_id": "dev-bypass-id",
                "environment_id": env.id, 
                "env_name": env.name, 
                "org_id": org.id, 
                "plan": org.plan
            }
            key_hash = "dev-bypass"
        finally:
            db.close()
    else:
        raw_key = _extract_raw_key(authorization)
        key_hash = hash_api_key(raw_key)
        key_data = await _resolve_api_key(key_hash)
    
    # Rate Limit (Bypass for dev mode)
    if settings.serve_rate_limit_rpm > 0 and key_hash != "dev-bypass":
        allowed, count, limit = await check_rate_limit(key_hash, settings.serve_rate_limit_rpm)
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    content_data, cache_hit = await _resolve_prompt(key_data["environment_id"], prompt_key)
    
    # Enhanced Substitution: vars list + direct query params
    query_params = dict(request.query_params)
    content, unfilled = _substitute_variables(content_data["content"], vars, query_params)
    
    latency_ms = int((time.monotonic() - t0) * 1000)
    cache_status = "HIT" if cache_hit else "MISS"

    # 📊 Telemetry: Log in background (skip for dev-bypass — no real api_key row)
    if key_hash != "dev-bypass":
        background_tasks.add_task(
            _log_serve_event_bg,
            org_id=key_data["org_id"],
            api_key_id=key_data["api_key_id"],
            prompt_id=content_data["prompt_id"],
            version_id=content_data["version_id"],
            environment_id=key_data["environment_id"],
            latency_ms=latency_ms,
            extra={"cache": cache_status, "unfilled": unfilled}
        )

    headers = {
        "X-PM-Version": str(content_data["version_num"]),
        "X-PM-Cache": cache_status,
        "X-PM-Latency": f"{latency_ms}ms"
    }

    if format == "json":
        return JSONResponse(
            content={
                "key": prompt_key, "content": content,
                "version": content_data["version_num"],
                "environment": key_data.get("env_name", ""),
                "latency_ms": latency_ms,
                "cache": cache_status,
                "unfilled": unfilled,
                "served_at": datetime.now(timezone.utc).isoformat(),
            },
            headers=headers
        )
    
    return PlainTextResponse(content=content, headers=headers)

