"""
Projects + Environments — /api/v1/projects
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Environment, Organisation, OrgMember
from app.core.auth import get_current_user_and_org

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("")
async def list_projects(
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org context")

    projects = db.query(Project).filter(Project.org_id == member.org_id).all()

    result = []
    for p in projects:
        envs = db.query(Environment).filter(Environment.project_id == p.id).all()
        result.append({
            "id": p.id,
            "name": p.name,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "environments": [{
                "id": e.id,
                "name": e.name,
                "display_name": e.display_name,
                "color": e.color,
                "is_protected": e.is_protected,
                "eval_pass_threshold": e.eval_pass_threshold,
            } for e in envs]
        })

    return {"projects": result}
