"""Organisation + team management — /api/v1/orgs"""

import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Organisation, OrgMember, User, AuditLog
from app.core.auth import get_current_user_and_org, require_role, hash_password, ROLE_HIERARCHY

router = APIRouter(prefix="/api/v1/orgs", tags=["orgs"])


class InviteIn(BaseModel):
    email: str
    role: str = "editor"


class UpdateRoleIn(BaseModel):
    role: str


@router.get("/{org_id}/members")
async def list_members(
    org_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member or member.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    rows = (
        db.query(OrgMember, User)
        .join(User, OrgMember.user_id == User.id)
        .filter(OrgMember.org_id == org_id)
        .order_by(OrgMember.joined_at.asc())
        .all()
    )
    return {"members": [{
        "user_id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": m.role,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    } for m, u in rows]}


@router.post("/{org_id}/members")
async def invite_member(
    org_id: str,
    body: InviteIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member or member.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    require_role(member, "admin")

    if body.role not in ROLE_HIERARCHY:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")
    if ROLE_HIERARCHY[body.role] >= ROLE_HIERARCHY[member.role]:
        raise HTTPException(status_code=403, detail="Cannot invite to a role equal or higher than yours")

    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    existing_user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    temp_password = None

    if existing_user:
        if db.query(OrgMember).filter(
            OrgMember.user_id == existing_user.id, OrgMember.org_id == org_id
        ).first():
            raise HTTPException(status_code=409, detail="User is already a member")
        db.add(OrgMember(org_id=org_id, user_id=existing_user.id, role=body.role))
        db.add(AuditLog(
            org_id=org_id, actor_id=user.id, actor_email=user.email,
            action="member.invited", resource_type="member", resource_id=existing_user.id,
            extra={"email": body.email, "role": body.role}
        ))
        db.commit()
        message = f"{body.email} added to {org.name}"
    else:
        temp_password = secrets.token_urlsafe(12)
        new_user = User(email=body.email.lower().strip(), hashed_pw=hash_password(temp_password), full_name="")
        db.add(new_user)
        db.flush()
        db.add(OrgMember(org_id=org_id, user_id=new_user.id, role=body.role))
        db.add(AuditLog(
            org_id=org_id, actor_id=user.id, actor_email=user.email,
            action="member.invited_new", resource_type="member", resource_id=new_user.id,
            extra={"email": body.email, "role": body.role}
        ))
        db.commit()
        message = f"Invite sent to {body.email}"

    # Invite email — awaited directly. Vercel kills create_task after response returns.
    if temp_password:
        try:
            from app.core.email import send_invite
            await send_invite(
                invitee_email=body.email,
                inviter_name=user.full_name or user.email,
                org_name=org.name,
                role=body.role,
                temp_password=temp_password
            )
        except Exception:
            pass  # Email failure never blocks the invite

    return {"message": message}


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(
    org_id: str,
    user_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member or member.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    require_role(member, "admin")

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    target = db.query(OrgMember).filter(
        OrgMember.user_id == user_id, OrgMember.org_id == org_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if ROLE_HIERARCHY.get(target.role, 0) >= ROLE_HIERARCHY.get(member.role, 0):
        raise HTTPException(status_code=403, detail="Cannot remove someone with equal or higher role")

    db.add(AuditLog(
        org_id=org_id, actor_id=user.id, actor_email=user.email,
        action="member.removed", resource_type="member", resource_id=user_id
    ))
    db.delete(target)
    db.commit()
    return {"message": "Member removed"}
