import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, field_validator
from app.database import get_db
from app.models import (
    Prompt, PromptVersion, Environment, OrgMember, AuditLog, User, Organisation
)
from app.core.auth import get_current_user_and_org, require_role
from app.serve.cache import invalidate_prompt_cache
from app.core.policy import redact_identified_secrets, analyze_prompt_safety
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
            raise ValueError("Key format invalid")
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

def _detect_variables(content: str) -> dict:
    found = re.findall(r'\{\{([\w_]+)\}\}', content)
    return {v: "" for v in set(found)}

def _next_version_num(prompt_id: str, db: Session) -> int:
    from sqlalchemy import func
    result = db.query(func.max(PromptVersion.version_num)).filter(
        PromptVersion.prompt_id == prompt_id
    ).scalar()
    return (result + 1) if result is not None else 1

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

def _serialize_prompt(p: Prompt) -> dict:
    live = p.live_version
    return {
        "id": p.id,
        "key": p.key,
        "description": p.description,
        "tags": p.tags or [],
        "version_count": len(p.versions),
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
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    prompts = (
        db.query(Prompt)
        .options(joinedload(Prompt.versions), joinedload(Prompt.live_version))
        .filter(Prompt.environment_id == environment_id)
        .order_by(Prompt.created_at.desc())
        .all()
    )
    return {"prompts": [_serialize_prompt(p) for p in prompts]}

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
    
    ts = datetime.utcnow()
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="prompt.created", resource_type="prompt", resource_id=prompt.id,
        extra={"key": body.key, "env": body.environment_id, "policy_risks": [r[0] for r in risks]},
        created_at=ts,
        integrity_hash=_generate_integrity_hash("prompt.created", prompt.id, ts)
    ))
    db.commit()
    db.refresh(prompt)
    return {"prompt": _serialize_prompt(prompt)}

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
            v = PromptVersion(
                prompt_id=prompt_id,
                version_num=vnum,
                content=body.content,
                commit_message=body.commit_message or f"Version {vnum}",
                variables=_detect_variables(body.content),
                status="draft",
                proposed_by_id=user.id,
                parent_content=parent_content,
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
        raise HTTPException(status_code=400, detail="Not draft")
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
                env_name="production",
                note=body.note,
                dashboard_url=settings.frontend_url
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
    if v.status not in ("pending_review", "draft"):
        raise HTTPException(status_code=400, detail="Cannot approve")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if prompt and prompt.live_version_id and prompt.live_version_id != version_id:
        old = db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
        if old:
            old.status = "archived"
    v.status = "approved"
    v.approved_by_id = user.id
    v.approved_at = datetime.utcnow()
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
            if requester:
                await send_version_approved(
                    requester_email=requester.email,
                    approver_name=user.full_name or user.email,
                    prompt_key=prompt.key if prompt else "",
                    version_num=v.version_num,
                    env_name="production"
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
                    dashboard_url=settings.frontend_url
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
                approved_at=datetime.utcnow(),
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
