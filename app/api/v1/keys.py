from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import (generate_api_key, get_current_user_and_org,
                           require_role)
from app.database import get_db
from app.models import ApiKey, AuditLog, Environment
from app.serve.cache import invalidate_key_cache

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


class CreateKeyIn(BaseModel):
    environment_id: str
    name: str


@router.get("")
async def list_keys(
    environment_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.environment_id == environment_id, ApiKey.is_active)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return {
        "keys": [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.key_prefix,
                "is_active": k.is_active,
                "created_at": k.created_at.isoformat() if k.created_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ]
    }


@router.post("")
async def create_key(
    body: CreateKeyIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db),
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    env = db.query(Environment).filter(Environment.id == body.environment_id).first()
    if not env:
        raise HTTPException(status_code=404, detail="Not found")
    full_key, key_hash, key_prefix = generate_api_key(env.name)
    api_key = ApiKey(
        environment_id=body.environment_id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by_id=user.id,
    )
    db.add(api_key)
    from app.services.audit_service import AuditService
    AuditService.log_action(
        db=db,
        org_id=member.org_id,
        actor_id=user.id,
        actor_email=user.email,
        action="key.created",
        resource_type="key",
        resource_id=api_key.id,
        extra={"name": body.name, "env": env.name},
    )
    db.commit()
    return {"key": full_key, "prefix": key_prefix, "id": api_key.id, "message": "Copy"}


@router.delete("/{key_id}")
async def revoke_key(
    key_id: str, auth=Depends(get_current_user_and_org), db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    k = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not k:
        raise HTTPException(status_code=404, detail="Not found")
    k.is_active = False
    from app.services.audit_service import AuditService
    AuditService.log_action(
        db=db,
        org_id=member.org_id,
        actor_id=user.id,
        actor_email=user.email,
        action="key.revoked",
        resource_type="key",
        resource_id=key_id,
        extra={"name": k.name},
    )
    db.commit()
    await invalidate_key_cache(k.key_hash)
    return {"message": "Revoked"}


@router.post("/{key_id}/rotate")
async def rotate_key(
    key_id: str, auth=Depends(get_current_user_and_org), db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    require_role(member, "engineer")
    old = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not old:
        raise HTTPException(status_code=404, detail="Not found")
    env = db.query(Environment).filter(Environment.id == old.environment_id).first()
    full_key, key_hash, key_prefix = generate_api_key(env.name if env else "production")
    old.is_active = False
    new_key = ApiKey(
        environment_id=old.environment_id,
        name=old.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by_id=user.id,
    )
    db.add(new_key)
    from app.services.audit_service import AuditService
    AuditService.log_action(
        db=db,
        org_id=member.org_id,
        actor_id=user.id,
        actor_email=user.email,
        action="key.rotated",
        resource_type="key",
        resource_id=key_id,
        extra={"name": old.name},
    )
    old_hash = old.key_hash
    db.commit()
    await invalidate_key_cache(old_hash)
    return {
        "key": full_key,
        "prefix": key_prefix,
        "id": new_key.id,
        "message": "Rotated",
    }
