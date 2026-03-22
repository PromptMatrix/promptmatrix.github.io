"""Approval queue — /api/v1/approvals"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import PromptVersion, Prompt, Environment, User, Organisation, Project
from app.core.auth import get_current_user_and_org

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@router.get("")
async def list_approvals(
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org context")

    # Get all environments in this org
    projects = db.query(Project).filter(Project.org_id == member.org_id).all()
    project_ids = [p.id for p in projects]
    envs = db.query(Environment).filter(Environment.project_id.in_(project_ids)).all()
    env_ids = [e.id for e in envs]
    env_map = {e.id: e for e in envs}

    # Get all prompts in these environments
    prompts = db.query(Prompt).filter(Prompt.environment_id.in_(env_ids)).all()
    prompt_ids = [p.id for p in prompts]
    prompt_map = {p.id: p for p in prompts}

    # Get all pending_review versions
    pending = (
        db.query(PromptVersion)
        .options(
            joinedload(PromptVersion.proposed_by),
        )
        .filter(
            PromptVersion.prompt_id.in_(prompt_ids),
            PromptVersion.status == "pending_review"
        )
        .order_by(PromptVersion.created_at.asc())
        .all()
    )

    result = []
    for v in pending:
        p = prompt_map.get(v.prompt_id)
        env = env_map.get(p.environment_id) if p else None
        result.append({
            "approval_request_id": v.id,  # used by frontend
            "version": {
                "id": v.id,
                "version_num": v.version_num,
                "content": v.content,
                "parent_content": v.parent_content,
                "commit_message": v.commit_message,
                "status": v.status,
                "eval_score": v.last_eval_score,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            },
            "prompt": {"id": p.id, "key": p.key} if p else None,
            "environment": {
                "id": env.id, "name": env.name,
                "color": env.color, "display_name": env.display_name
            } if env else None,
            "requested_by": {
                "id": v.proposed_by.id,
                "email": v.proposed_by.email,
                "name": v.proposed_by.full_name
            } if v.proposed_by else None,
            "note": v.approval_note,
        })

    return {"pending": result}
