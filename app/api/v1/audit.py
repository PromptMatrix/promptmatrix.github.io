from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_and_org
from app.database import get_db
from app.models import AuditLog

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
async def list_audit(
    resource_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    q = db.query(AuditLog).filter(AuditLog.org_id == member.org_id)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    logs = (
        q.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(min(limit, 200))
        .all()
    )
    return {
        "logs": [
            {
                "id": l.id,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "actor_email": l.actor_email,
                "extra": l.extra or {},
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ]
    }
