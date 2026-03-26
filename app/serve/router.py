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


def _rk(a):
    if not a or not a.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return a[7:]


async def _ak(h, d=None):
    c = await get_cached_key(h)
    if c is not None:
        return c
    db = d or _db()
    try:
        r = db.query(ApiKey).filter(ApiKey.key_hash == h, ApiKey.is_active == True).first()
        if not r:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if r.expires_at and r.expires_at < dt.datetime.utcnow():
            raise HTTPException(status_code=401, detail="API key expired")
        e = db.query(Environment).filter(Environment.id == r.environment_id).first()
        if not e:
            raise HTTPException(status_code=401, detail="Environment not found")
        p = db.query(Project).filter(Project.id == e.project_id).first()
        if not p:
            raise HTTPException(status_code=401, detail="Project not found")
        o = db.query(Organisation).filter(Organisation.id == p.org_id).first()
        if not o:
            raise HTTPException(status_code=401, detail="Organisation not found")
        kd = {"environment_id": e.id, "env_name": e.name, "org_id": o.id, "plan": o.plan}
        await cache_key(h, e.id, o.id, o.plan, e.name)
        r.last_used_at = dt.datetime.utcnow()
        db.commit()
        return kd
    finally:
        if d is None:
            db.close()


async def _rp(eid, pk):
    c = await get_cached_prompt(eid, pk)
    if c is not None:
        return c
    db = _db()
    try:
        pr = db.query(Prompt).filter(Prompt.environment_id == eid, Prompt.key == pk).first()
        if not pr:
            raise HTTPException(status_code=404, detail=f"Prompt '{pk}' not found in this environment")
        if not pr.live_version_id:
            raise HTTPException(status_code=404, detail=f"Prompt '{pk}' has no approved version yet")
        vr = db.query(PromptVersion).filter(
            PromptVersion.id == pr.live_version_id, PromptVersion.status == "approved"
        ).first()
        if not vr:
            raise HTTPException(status_code=404, detail=f"No approved version for '{pk}'")
        cd = {"content": vr.content, "version_num": vr.version_num, "version_id": vr.id,
              "variables": vr.variables or {}}
        await cache_prompt(eid, pk, cd["content"], cd["version_num"], cd["version_id"], cd["variables"])
        return cd
    finally:
        db.close()


def _vs(content, vars_str):
    if not vars_str:
        return content
    for pair in vars_str.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            content = content.replace(f"{{{{{k.strip()}}}}}", v.strip())
    return content


@router.get("/pm/serve/{prompt_key:path}")
async def serve_prompt(
    prompt_key: str,
    request: Request,
    authorization: Optional[str] = Header(None),
    format: str = "text",
    vars: Optional[str] = None,
):
    t0 = time.monotonic()
    rk = _rk(authorization)
    kh = hash_api_key(rk)
    kd = await _ak(kh)
    eid = kd["environment_id"]
    if settings.serve_rate_limit_rpm > 0:
        ok, cnt, lim = await check_rate_limit(kh, settings.serve_rate_limit_rpm)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {lim} requests/minute per key"},
                headers={"X-RateLimit-Limit": str(lim), "X-RateLimit-Remaining": "0", "Retry-After": "60"}
            )
    cd = await _rp(eid, prompt_key)
    content = _vs(cd["content"], vars)
    ms = round((time.monotonic() - t0) * 1000, 2)
    if format == "json":
        return {"key": prompt_key, "content": content, "version": cd["version_num"],
                "version_id": cd["version_id"], "environment": kd.get("env_name", ""),
                "variables": cd["variables"], "latency_ms": ms,
                "served_at": dt.datetime.utcnow().isoformat() + "Z"}
    return PlainTextResponse(
        content=content,
        headers={"X-PM-Version": str(cd["version_num"]), "X-PM-Latency": str(ms)}
    )
