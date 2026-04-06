import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_user_and_org, require_role
from app.database import get_db
from app.models import AuditLog, Environment, Prompt, PromptVersion
from app.serve.cache import invalidate_prompt_cache
from app.services.prompt_service import PromptService

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


class CreatePromptIn(BaseModel):
    environment_id: str
    key: str
    content: str
    description: str = ""
    commit_message: str = "Initial version"
    tags: list = []

    @field_validator("key")
    def key_format(cls, v):
        if not re.match(r"^[a-z0-9._\-]{1,200}$", v):
            raise ValueError(
                "Key format invalid. Use lowercase letters, digits, dots, dashes, underscores only."
            )
        return v


class CreateVersionIn(BaseModel):
    content: str
    commit_message: str = ""


class SubmitReviewIn(BaseModel):
    note: str = ""


class ApproveIn(BaseModel):
    note: str = ""


class RejectIn(BaseModel):
    reason: str


class PromoteIn(BaseModel):
    target_environment_id: str
    auto_approve: bool = False


class AssistIn(BaseModel):
    task_description: str = ""
    existing_content: str = ""
    mode: str = "improve"
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5"
    api_key: str = ""
    eval_key_id: str = ""


def _serialize_version(v: PromptVersion, is_live: bool = False) -> dict:
    return {
        "id": v.id,
        "version_num": v.version_num,
        "content": v.content,
        "commit_message": v.commit_message,
        "status": v.status,
        "variables": v.variables or {},
        "parent_content": v.parent_content,
        "proposed_by": (
            {"email": v.proposed_by.email, "name": v.proposed_by.full_name}
            if v.proposed_by
            else None
        ),
        "approved_by": (
            {"email": v.approved_by.email, "name": v.approved_by.full_name}
            if v.approved_by
            else None
        ),
        "last_eval_score": v.last_eval_score,
        "last_eval_passed": v.last_eval_passed,
        "last_eval_at": v.last_eval_at.isoformat() if v.last_eval_at else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "approved_at": v.approved_at.isoformat() if v.approved_at else None,
        "is_live": is_live,
    }


def _serialize_prompt(p: Prompt, version_count: int = None) -> dict:
    live = p.live_version
    return {
        "id": p.id,
        "key": p.key,
        "description": p.description,
        "tags": p.tags or [],
        "version_count": version_count if version_count is not None else 0,
        "live_version": _serialize_version(live, True) if live else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_prompts(
    environment_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")

    version_counts_subq = (
        db.query(PromptVersion.prompt_id, func.count(PromptVersion.id).label("cnt"))
        .group_by(PromptVersion.prompt_id)
        .subquery()
    )

    prompts = (
        db.query(Prompt)
        .options(
            joinedload(Prompt.live_version).joinedload(PromptVersion.proposed_by),
            joinedload(Prompt.live_version).joinedload(PromptVersion.approved_by),
        )
        .filter(Prompt.environment_id == environment_id)
        .order_by(Prompt.created_at.desc())
        .all()
    )

    count_rows = (
        db.query(version_counts_subq)
        .filter(version_counts_subq.c.prompt_id.in_([p.id for p in prompts]))
        .all()
        if prompts
        else []
    )
    count_map = {row.prompt_id: row.cnt for row in count_rows}

    return {"prompts": [_serialize_prompt(p, count_map.get(p.id, 0)) for p in prompts]}


@router.post("")
async def create_prompt(
    body: CreatePromptIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "editor")

    service = PromptService(db)
    prompt = service.create_prompt(
        env_id=body.environment_id,
        key=body.key,
        content=body.content,
        user_id=user.id,
        user_email=user.email,
        org_id=member.org_id,
        description=body.description,
        commit_message=body.commit_message,
        tags=body.tags,
    )

    vc = (
        db.query(func.count(PromptVersion.id))
        .filter(PromptVersion.prompt_id == prompt.id)
        .scalar()
    )
    return {"prompt": _serialize_prompt(prompt, version_count=vc)}


@router.get("/{prompt_id}")
async def get_prompt(
    prompt_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    prompt = (
        db.query(Prompt)
        .options(
            joinedload(Prompt.versions).joinedload(PromptVersion.proposed_by),
            joinedload(Prompt.versions).joinedload(PromptVersion.approved_by),
            joinedload(Prompt.live_version),
        )
        .filter(Prompt.id == prompt_id)
        .first()
    )
    if not prompt:
        raise HTTPException(status_code=404, detail="Not found")
    lv_id = prompt.live_version_id
    versions = sorted(prompt.versions, key=lambda v: v.version_num)
    return {
        "prompt": _serialize_prompt(prompt),
        "versions": [_serialize_version(v, v.id == lv_id) for v in versions],
    }


@router.post("/{prompt_id}/versions")
async def create_version(
    prompt_id: str,
    body: CreateVersionIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "editor")

    service = PromptService(db)
    v = service.create_version(
        prompt_id=prompt_id,
        content=body.content,
        user_id=user.id,
        user_email=user.email,
        org_id=member.org_id,
        commit_message=body.commit_message,
    )
    return {"version": _serialize_version(v)}


@router.post("/{prompt_id}/versions/{version_id}/submit")
async def submit_for_review(
    prompt_id: str,
    version_id: str,
    body: SubmitReviewIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")

    service = PromptService(db)
    # Guard: cannot submit if already pending or approved
    v_check = (
        db.query(PromptVersion)
        .filter(PromptVersion.id == version_id, PromptVersion.prompt_id == prompt_id)
        .first()
    )
    if not v_check:
        raise HTTPException(status_code=404, detail="Version not found")
    if v_check.status == "pending_review":
        raise HTTPException(status_code=400, detail="Already submitted for review")
    if v_check.status in ("approved", "archived"):
        raise HTTPException(
            status_code=400, detail="Cannot submit an already approved/archived version"
        )
    v = await service.submit_for_review(prompt_id, version_id, body.note, user, member)
    return {"version": _serialize_version(v)}


@router.post("/{prompt_id}/versions/{version_id}/approve")
async def approve_version(
    prompt_id: str,
    version_id: str,
    body: ApproveIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")

    service = PromptService(db)
    v = await service.approve_version(prompt_id, version_id, body.note, user, member)
    return {"version": _serialize_version(v), "message": "Live"}


@router.post("/{prompt_id}/versions/{version_id}/reject")
async def reject_version(
    prompt_id: str,
    version_id: str,
    body: RejectIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")

    service = PromptService(db)
    v = await service.reject_version(prompt_id, version_id, body.reason, user, member)
    return {"version": _serialize_version(v)}


@router.post("/{prompt_id}/versions/{version_id}/rollback")
async def rollback_to_version(
    prompt_id: str,
    version_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")

    service = PromptService(db)
    v = await service.rollback_prompt(
        prompt_id, version_id, user.id, user.email, member.org_id
    )
    return {"message": "Success", "version": _serialize_version(v)}


@router.post("/{prompt_id}/versions/{version_id}/quick-approve")
async def quick_approve_version(
    prompt_id: str,
    version_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    """1-click draft-to-live for local development only. Returns 403 in production."""
    from app.config import get_settings

    if get_settings().app_env != "development":
        raise HTTPException(
            status_code=403,
            detail="Quick approve is only available in local/development mode.",
        )
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")

    service = PromptService(db)
    v = await service.approve_version(
        prompt_id, version_id, "Quick approved (local mode)", user, member,
        quick_approve=True,
    )
    return {"version": _serialize_version(v, is_live=True), "message": "Live"}


@router.post("/{prompt_id}/promote")
async def promote_prompt(
    prompt_id: str,
    body: PromoteIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    """Handle promotion from one environment to another."""
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")

    service = PromptService(db)
    prompt, version = await service.promote_prompt(
        prompt_id=prompt_id,
        target_env_id=body.target_environment_id,
        user_id=user.id,
        user_email=user.email,
        org_id=member.org_id,
        auto_approve=body.auto_approve,
    )

    return {
        "prompt_id": prompt.id,
        "version_id": version.id,
        "status": version.status,
        "target_environment_id": body.target_environment_id,
    }


@router.post("/assist")
async def writing_assist(
    body: AssistIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    """Phase 1 UX: LLM writing assist. BYOK — key is never stored or logged."""
    import json

    import httpx

    from app.api.v1.evals import PROVIDER_CONFIG, VALID_PROVIDERS

    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")

    if not body.api_key and not body.eval_key_id:
        raise HTTPException(
            status_code=400,
            detail="Provide api_key (BYOK) or eval_key_id in request body",
        )
    if body.provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider. Valid: {', '.join(VALID_PROVIDERS)}",
        )

    # Resolve API key: BYOK preferred
    key = body.api_key
    if not key and body.eval_key_id:
        from app.core.auth import decrypt_api_key
        from app.models import EvalKey

        ek = (
            db.query(EvalKey)
            .filter(EvalKey.id == body.eval_key_id, EvalKey.org_id == member.org_id)
            .first()
        )
        if not ek:
            raise HTTPException(status_code=404, detail="Eval key not found")
        key = decrypt_api_key(ek.encrypted_key)

    # Build mode-specific prompt
    if body.mode == "generate":
        instruction = f"""You are a senior prompt engineer. Write a complete, high-quality system prompt for the following task.
Include {{{{variables}}}} for any dynamic values. Be specific and use imperative instructions.
Task: {body.task_description}
Respond with JSON only: {{"content": "...", "variables": ["var1", ...], "rationale": "why this approach"}}"""
    elif body.mode == "critique":
        instruction = f"""You are a senior prompt engineer reviewing a system prompt. Identify concrete issues and provide specific fixes.
Respond with JSON only: {{"issues": [{{"problem": "...", "fix": "..."}}, ...], "overall_score": 0-10, "priority_fix": "..."}}
Prompt to critique:
---
{body.existing_content}
---"""
    else:  # improve (default)
        instruction = f"""You are a senior prompt engineer. Improve the following system prompt for clarity, specificity, and output format guidance.
Keep the core intent. Use {{{{variables}}}} for dynamic values.
Respond with JSON only: {{"content": "...", "changes": ["...", ...], "rationale": "...", "variables": ["var1", ...]}}
Prompt to improve:
---
{body.existing_content}
---
Context / goal: {body.task_description or '(not specified)'}"""

    cfg = PROVIDER_CONFIG[body.provider]
    actual_key = key
    try:
        url = cfg.get("get_url", lambda m, k: cfg["url"])(body.model, actual_key)
        headers = cfg["get_headers"](actual_key)
        req_body = cfg["get_body"](body.model, instruction)
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=req_body)
            resp.raise_for_status()
        raw = resp.json()
        text = cfg["parse_text"](raw)
        tokens_in, tokens_out = cfg["parse_tokens"](raw)
        clean = text.strip().replace("```json", "").replace("```", "").strip()
        # Try to parse JSON; fall back to raw text if LLM didn't follow format
        try:
            data = json.loads(clean)
        except Exception:
            data = {"content": clean, "rationale": "Raw response (JSON parse failed)"}
        return {
            "mode": body.mode,
            "provider": body.provider,
            "model": body.model,
            "result": data,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM assist failed: {str(e)}")
    finally:
        del actual_key  # BYOK: explicit scope delete — key never stored


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "admin")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Not found")
    env = db.query(Environment).filter(Environment.id == prompt.environment_id).first()
    if env:
        await invalidate_prompt_cache(env.id, prompt.key)
    db.add(
        AuditLog(
            org_id=member.org_id,
            actor_id=user.id,
            actor_email=user.email,
            action="prompt.deleted",
            resource_type="prompt",
            resource_id=prompt_id,
            extra={"key": prompt.key},
        )
    )
    db.delete(prompt)
    db.commit()
    return {"message": "Deleted"}
