import re
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel, field_validator
from app.database import get_db
from app.models import (
    Prompt, PromptVersion, Environment, OrgMember, AuditLog, User, Organisation, Project
)
from app.core.auth import get_current_user_and_org, require_role
from app.serve.cache import invalidate_prompt_cache
from app.core.policy import redact_identified_secrets, analyze_prompt_safety
from app.config import get_settings
import hashlib

def _generate_integrity_hash(action: str, resource_id: str, ts: datetime) -> str:
    """Generate a SHA-256 hash to ensure log integrity."""
    ctx = f"{action}:{resource_id}:{ts.isoformat()}"
    return hashlib.sha256(ctx.encode()).hexdigest()

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
        if not re.match(r'^[a-z0-9._\-]{1,200}$', v):
            raise ValueError("Key format invalid. Use lowercase letters, digits, dots, dashes, underscores only.")
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
    auto_approve: bool = False  # only works in dev mode

class AssistIn(BaseModel):
    task_description: str = ""
    existing_content: str = ""
    mode: str = "improve"  # generate | improve | critique
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5"
    api_key: str = ""  # BYOK: never stored, never logged
    eval_key_id: str = ""  # use saved org key

def _detect_variables(content: str) -> dict:
    found = re.findall(r'\{\{([\w_]+)\}\}', content)
    return {v: "" for v in set(found)}


def _next_version_num(prompt_id: str, db: Session) -> int:
    result = db.query(func.max(PromptVersion.version_num)).filter(
        PromptVersion.prompt_id == prompt_id
    ).scalar()
    return (result + 1) if result is not None else 1


def _count_versions(prompt_id: str, db: Session) -> int:
    return db.query(func.count(PromptVersion.id)).filter(
        PromptVersion.prompt_id == prompt_id
    ).scalar() or 0


def _serialize_version(v: PromptVersion, is_live: bool = False) -> dict:
    return {
        "id": v.id,
        "version_num": v.version_num,
        "content": v.content,
        "commit_message": v.commit_message,
        "status": v.status,
        "variables": v.variables or {},
        "parent_content": v.parent_content,
        "proposed_by": {"email": v.proposed_by.email, "name": v.proposed_by.full_name} if v.proposed_by else None,
        "approved_by": {"email": v.approved_by.email, "name": v.approved_by.full_name} if v.approved_by else None,
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
    db: Session = Depends(get_db)
):
    """BUG-03 FIX: Does NOT joinedload all version content. Loads live_version only, counts versions via subquery."""
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")

    # Count versions per prompt in a single subquery (not N+1)
    version_counts_subq = (
        db.query(PromptVersion.prompt_id, func.count(PromptVersion.id).label("cnt"))
        .group_by(PromptVersion.prompt_id)
        .subquery()
    )

    prompts = (
        db.query(Prompt)
        .options(joinedload(Prompt.live_version))  # only live version, NOT all versions
        .filter(Prompt.environment_id == environment_id)
        .order_by(Prompt.created_at.desc())
        .all()
    )

    # Build count map from subquery
    count_rows = db.query(version_counts_subq).filter(
        version_counts_subq.c.prompt_id.in_([p.id for p in prompts])
    ).all() if prompts else []
    count_map = {row.prompt_id: row.cnt for row in count_rows}

    return {"prompts": [_serialize_prompt(p, count_map.get(p.id, 0)) for p in prompts]}

@router.post("")
async def create_prompt(
    body: CreatePromptIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "editor")
    if db.query(Prompt).filter(
        Prompt.environment_id == body.environment_id,
        Prompt.key == body.key
    ).first():
        raise HTTPException(status_code=409, detail="Key exists")
    prompt = Prompt(
        environment_id=body.environment_id,
        key=body.key,
        description=body.description,
        tags=body.tags,
    )
    db.add(prompt)
    db.flush()
    # Security Policy: Redact Secrets
    content_safe = redact_identified_secrets(body.content)
    risks = analyze_prompt_safety(body.content)
    
    v = PromptVersion(
        prompt_id=prompt.id,
        version_num=1,
        content=content_safe,
        commit_message=body.commit_message or "Initial version",
        variables=_detect_variables(content_safe),
        status="draft",
        proposed_by_id=user.id,
        approval_note = f"Policy Check: {len(risks)} risks detected." if risks else "Policy Check: Pass.",
    )
    db.add(v)
    db.flush()
    
    ts = datetime.now(timezone.utc)
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="prompt.created", resource_type="prompt", resource_id=prompt.id,
        extra={"key": body.key, "env": body.environment_id, "policy_risks": [r[0] for r in risks]},
        created_at=ts,
        integrity_hash=_generate_integrity_hash("prompt.created", prompt.id, ts)
    ))
    db.commit()
    db.refresh(prompt)
    vc = _count_versions(prompt.id, db)
    return {"prompt": _serialize_prompt(prompt, version_count=vc)}

@router.get("/{prompt_id}")
async def get_prompt(
    prompt_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    prompt = (
        db.query(Prompt)
        .options(
            joinedload(Prompt.versions).joinedload(PromptVersion.proposed_by),
            joinedload(Prompt.versions).joinedload(PromptVersion.approved_by),
            joinedload(Prompt.live_version)
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
        "versions": [_serialize_version(v, v.id == lv_id) for v in versions]
    }

@router.post("/{prompt_id}/versions")
async def create_version(
    prompt_id: str,
    body: CreateVersionIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "editor")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Not found")
    parent_content = None
    if prompt.live_version_id:
        live = db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
        if live:
            parent_content = live.content
    from sqlalchemy.exc import IntegrityError
    for attempt in range(3):
        try:
            vnum = _next_version_num(prompt_id, db)
            # Security Policy: Redact secrets in new version content
            from app.core.policy import redact_identified_secrets, analyze_prompt_safety
            content_safe = redact_identified_secrets(body.content)
            risks = analyze_prompt_safety(body.content)
            v = PromptVersion(
                prompt_id=prompt_id,
                version_num=vnum,
                content=content_safe,
                commit_message=body.commit_message or f"Version {vnum}",
                variables=_detect_variables(content_safe),
                status="draft",
                proposed_by_id=user.id,
                parent_content=parent_content,
                approval_note=f"Policy Check: {len(risks)} risks detected." if risks else "Policy Check: Pass.",
            )
            db.add(v)
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise HTTPException(status_code=409, detail="Conflict")
            continue
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="version.created", resource_type="version", resource_id=v.id,
        extra={"prompt_key": prompt.key, "version_num": vnum}
    ))
    db.commit()
    db.refresh(v)
    return {"version": _serialize_version(v)}

@router.post("/{prompt_id}/versions/{version_id}/submit")
async def submit_for_review(
    prompt_id: str,
    version_id: str,
    body: SubmitReviewIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    v = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.prompt_id == prompt_id
    ).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    if v.status != "draft":
        raise HTTPException(status_code=400, detail="Version must be in draft status to submit for review")
    v.status = "pending_review"
    v.approval_note = body.note
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="version.submitted", resource_type="version", resource_id=v.id,
        extra={"prompt_key": prompt.key if prompt else "", "note": body.note}
    ))
    db.commit()
    try:
        from app.core.email import send_approval_needed
        from app.config import get_settings
        settings = get_settings()
        # Resolve actual environment name
        _env = db.query(Environment).filter(Environment.id == prompt.environment_id).first() if prompt else None
        _env_name = _env.name if _env else "unknown"
        engineers = db.query(User).join(OrgMember).filter(
            OrgMember.org_id == member.org_id,
            OrgMember.role.in_(["engineer", "admin", "owner"])
        ).all()
        for eng in engineers:
            await send_approval_needed(
                approver_email=eng.email,
                requester_name=user.full_name or user.email,
                prompt_key=prompt.key if prompt else version_id,
                version_num=v.version_num,
                env_name=_env_name,
                note=body.note,
                dashboard_url=settings.app_url
            )
    except Exception:
        pass
    return {"version": _serialize_version(v)}

@router.post("/{prompt_id}/versions/{version_id}/approve")
async def approve_version(
    prompt_id: str,
    version_id: str,
    body: ApproveIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    v = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.prompt_id == prompt_id
    ).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    if v.status != "pending_review":
        raise HTTPException(status_code=400, detail="Version must be in pending_review status to approve. Submit it for review first.")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if prompt and prompt.live_version_id and prompt.live_version_id != version_id:
        old = db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
        if old:
            old.status = "archived"
    v.status = "approved"
    v.approved_by_id = user.id
    v.approved_at = datetime.now(timezone.utc)
    v.approval_note = body.note
    if prompt:
        prompt.live_version_id = v.id
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="version.approved", resource_type="version", resource_id=v.id,
        extra={"prompt_key": prompt.key if prompt else "", "version_num": v.version_num}
    ))
    db.commit()
    if prompt:
        env = db.query(Environment).filter(Environment.id == prompt.environment_id).first()
        if env:
            await invalidate_prompt_cache(env.id, prompt.key)
    try:
        from app.core.email import send_version_approved
        if v.proposed_by_id:
            requester = db.query(User).filter(User.id == v.proposed_by_id).first()
            _env_name_approve = env.name if env else "unknown"
            if requester:
                await send_version_approved(
                    requester_email=requester.email,
                    approver_name=user.full_name or user.email,
                    prompt_key=prompt.key if prompt else "",
                    version_num=v.version_num,
                    env_name=_env_name_approve
                )
    except Exception:
        pass
    return {"version": _serialize_version(v), "message": "Live"}

@router.post("/{prompt_id}/versions/{version_id}/reject")
async def reject_version(
    prompt_id: str,
    version_id: str,
    body: RejectIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    v = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.prompt_id == prompt_id
    ).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    v.status = "rejected"
    v.rejected_by_id = user.id
    v.rejection_reason = body.reason
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="version.rejected", resource_type="version", resource_id=v.id,
        extra={"reason": body.reason, "prompt_key": prompt.key if prompt else ""}
    ))
    db.commit()
    try:
        from app.core.email import send_version_rejected
        from app.config import get_settings
        settings = get_settings()
        if v.proposed_by_id:
            requester = db.query(User).filter(User.id == v.proposed_by_id).first()
            if requester:
                await send_version_rejected(
                    requester_email=requester.email,
                    reviewer_name=user.full_name or user.email,
                    prompt_key=prompt.key if prompt else "",
                    version_num=v.version_num,
                    reason=body.reason,
                    dashboard_url=settings.app_url
                )
    except Exception:
        pass
    return {"version": _serialize_version(v)}

@router.post("/{prompt_id}/versions/{version_id}/rollback")
async def rollback_to_version(
    prompt_id: str,
    version_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    target = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.prompt_id == prompt_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Not found")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Not found")
    from sqlalchemy.exc import IntegrityError
    for attempt in range(3):
        try:
            vnum = _next_version_num(prompt_id, db)
            rollback_v = PromptVersion(
                prompt_id=prompt_id,
                version_num=vnum,
                content=target.content,
                commit_message=f"Rollback to v{target.version_num}",
                variables=target.variables,
                status="approved",
                proposed_by_id=user.id,
                approved_by_id=user.id,
                approved_at=datetime.now(timezone.utc),
                parent_content=prompt.live_version.content if prompt.live_version else None,
            )
            db.add(rollback_v)
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise HTTPException(status_code=409, detail="Conflict")
            continue
    if prompt.live_version_id:
        old = db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
        if old:
            old.status = "archived"
    prompt.live_version_id = rollback_v.id
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="version.rollback", resource_type="version", resource_id=rollback_v.id,
        extra={"rolled_back_to": target.version_num, "new_version": vnum, "prompt_key": prompt.key}
    ))
    db.commit()
    env = db.query(Environment).filter(Environment.id == prompt.environment_id).first()
    if env:
        await invalidate_prompt_cache(env.id, prompt.key)
    return {"message": "Success"}

@router.post("/{prompt_id}/versions/{version_id}/quick-approve")
async def quick_approve_version(
    prompt_id: str,
    version_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    """Phase 1 UX: 1-click draft-to-live. ONLY available in development/local mode."""
    settings = get_settings()
    if settings.app_env != "development":
        raise HTTPException(status_code=403, detail="Quick approve is only available in local/development mode.")
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    v = db.query(PromptVersion).filter(
        PromptVersion.id == version_id, PromptVersion.prompt_id == prompt_id
    ).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    if v.status not in ("draft", "pending_review"):
        raise HTTPException(status_code=400, detail=f"Cannot quick-approve from status '{v.status}'.")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    # Archive current live version
    if prompt.live_version_id and prompt.live_version_id != version_id:
        old = db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
        if old:
            old.status = "archived"
    v.status = "approved"
    v.approved_by_id = user.id
    v.approved_at = datetime.now(timezone.utc)
    v.approval_note = "Quick approved (local mode)"
    prompt.live_version_id = v.id
    ts = datetime.now(timezone.utc)
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="version.quick_approved", resource_type="version", resource_id=v.id,
        extra={"prompt_key": prompt.key, "version_num": v.version_num},
        integrity_hash=_generate_integrity_hash("version.quick_approved", v.id, ts)
    ))
    db.commit()
    env = db.query(Environment).filter(Environment.id == prompt.environment_id).first()
    if env:
        await invalidate_prompt_cache(env.id, prompt.key)
    return {"version": _serialize_version(v, is_live=True), "message": "Live"}


@router.post("/{prompt_id}/promote")
async def promote_prompt(
    prompt_id: str,
    body: PromoteIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    """Copy an approved version to a target environment as a new draft."""
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    source_prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not source_prompt or not source_prompt.live_version_id:
        raise HTTPException(status_code=404, detail="Source prompt has no live version to promote")
    target_env = db.query(Environment).filter(Environment.id == body.target_environment_id).first()
    if not target_env:
        raise HTTPException(status_code=404, detail="Target environment not found")
    live_v = db.query(PromptVersion).filter(PromptVersion.id == source_prompt.live_version_id).first()
    if not live_v:
        raise HTTPException(status_code=404, detail="Live version not found")
    # Find or create prompt in target env
    target_prompt = db.query(Prompt).filter(
        Prompt.environment_id == body.target_environment_id,
        Prompt.key == source_prompt.key
    ).first()
    if not target_prompt:
        target_prompt = Prompt(
            environment_id=body.target_environment_id,
            key=source_prompt.key,
            description=source_prompt.description,
            tags=source_prompt.tags,
        )
        db.add(target_prompt)
        db.flush()
    settings = get_settings()
    new_status = "approved" if (body.auto_approve and settings.app_env == "development") else "draft"
    vnum = _next_version_num(target_prompt.id, db)
    new_v = PromptVersion(
        prompt_id=target_prompt.id,
        version_num=vnum,
        content=live_v.content,
        commit_message=f"Promoted from {source_prompt.key} (v{live_v.version_num})",
        variables=live_v.variables,
        status=new_status,
        proposed_by_id=user.id,
        parent_content=target_prompt.live_version.content if target_prompt.live_version else "",
    )
    if new_status == "approved":
        new_v.approved_by_id = user.id
        new_v.approved_at = datetime.now(timezone.utc)
    db.add(new_v)
    db.flush()
    if new_status == "approved":
        if target_prompt.live_version_id:
            old = db.query(PromptVersion).filter(PromptVersion.id == target_prompt.live_version_id).first()
            if old:
                old.status = "archived"
        target_prompt.live_version_id = new_v.id
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="prompt.promoted", resource_type="prompt", resource_id=target_prompt.id,
        extra={"from_prompt_id": source_prompt.id, "from_version": live_v.version_num, "target_env": body.target_environment_id, "auto_approved": new_status == "approved"}
    ))
    db.commit()
    if new_status == "approved":
        await invalidate_prompt_cache(body.target_environment_id, target_prompt.key)
    return {"prompt_id": target_prompt.id, "version_id": new_v.id, "status": new_status, "target_environment_id": body.target_environment_id}


@router.post("/assist")
async def writing_assist(
    body: AssistIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    """Phase 1 UX: LLM writing assist. BYOK — key is never stored or logged."""
    import httpx, json
    from app.api.v1.evals import PROVIDER_CONFIG, VALID_PROVIDERS
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")

    if not body.api_key and not body.eval_key_id:
        raise HTTPException(status_code=400, detail="Provide api_key (BYOK) or eval_key_id in request body")
    if body.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid: {', '.join(VALID_PROVIDERS)}")

    # Resolve API key: BYOK preferred
    key = body.api_key
    if not key and body.eval_key_id:
        from app.models import EvalKey
        from app.core.auth import decrypt_api_key
        ek = db.query(EvalKey).filter(EvalKey.id == body.eval_key_id, EvalKey.org_id == member.org_id).first()
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
    db: Session = Depends(get_db)
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
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="prompt.deleted", resource_type="prompt", resource_id=prompt_id,
        extra={"key": prompt.key}
    ))
    db.delete(prompt)
    db.commit()
    return {"message": "Deleted"}
