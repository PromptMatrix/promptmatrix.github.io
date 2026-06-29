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
                "id": log_entry.id,
                "action": log_entry.action,
                "resource_type": log_entry.resource_type,
                "resource_id": log_entry.resource_id,
                "actor_email": log_entry.actor_email,
                "extra": log_entry.extra or {},
                "created_at": log_entry.created_at.isoformat() if log_entry.created_at else None,
            }
            for log_entry in logs
        ]
    }
