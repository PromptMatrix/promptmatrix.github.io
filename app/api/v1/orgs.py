from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_and_org, require_role
from app.database import get_db
from app.models import OrgMember, User

router = APIRouter(prefix="/api/v1/orgs", tags=["orgs"])


class InviteMemberIn(BaseModel):
    email: str
    role: str


@router.get("/{org_id}/members")
async def list_members(
    org_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member or member.org_id != org_id:
        raise HTTPException(status_code=403, detail="Not a member of this org")
    require_role(member, "viewer")

    members = db.query(OrgMember).filter(OrgMember.org_id == org_id).all()
    user_ids = [m.user_id for m in members]
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    return {
        "members": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "email": users_by_id[m.user_id].email if m.user_id in users_by_id else "unknown",
                "full_name": users_by_id[m.user_id].full_name if m.user_id in users_by_id else "",
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
            for m in members
        ]
    }


@router.post("/{org_id}/members")
async def invite_member(
    org_id: str,
    body: InviteMemberIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member or member.org_id != org_id:
        raise HTTPException(status_code=403, detail="Not a member of this org")
    require_role(member, "admin")

    target_user = (
        db.query(User).filter(User.email == body.email.lower().strip()).first()
    )
    if not target_user:
        raise HTTPException(
            status_code=404,
            detail="User not found. They must register first in local mode.",
        )

    existing = (
        db.query(OrgMember)
        .filter(OrgMember.org_id == org_id, OrgMember.user_id == target_user.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")

    new_member = OrgMember(
        org_id=org_id,
        user_id=target_user.id,
        role=body.role,
        invited_by_id=user.id,
    )
    db.add(new_member)
    db.commit()
    return {"message": "Member invited", "member_id": new_member.id}


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(
    org_id: str,
    user_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member or member.org_id != org_id:
        raise HTTPException(status_code=403, detail="Not a member of this org")
    require_role(member, "admin")

    target_member = (
        db.query(OrgMember)
        .filter(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
        .first()
    )
    if not target_member:
        raise HTTPException(status_code=404, detail="Member not found")

    if target_member.role == "owner":
        owner_count = (
            db.query(OrgMember)
            .filter(OrgMember.org_id == org_id, OrgMember.role == "owner")
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner")

    db.delete(target_member)
    db.commit()
    return {"message": "Member removed"}
