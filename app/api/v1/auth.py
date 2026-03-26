import re
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from app.database import get_db
from app.models import User, Organisation, OrgMember, Project, Environment, AuditLog
from app.core.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, get_current_user_and_org
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class RegisterIn(BaseModel):
    email: str
    password: str
    full_name: str = ""
    @field_validator("password")
    def pw_length(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
    @field_validator("email")
    def email_format(cls, v):
        if "@" not in v:
            raise ValueError("Invalid email")
        return v.lower().strip()

class LoginIn(BaseModel):
    email: str
    password: str

class RefreshIn(BaseModel):
    refresh_token: str

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug or "workspace"

def _unique_slug(base: str, db: Session) -> str:
    slug = base
    i = 1
    while db.query(Organisation).filter(Organisation.slug == slug).first():
        slug = f"{base}-{i}"
        i += 1
    return slug

def _build_auth_response(user: User, member: OrgMember, org: Organisation) -> dict:
    access = create_access_token(user.id, org.id)
    refresh = create_refresh_token(user.id, org.id)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "active_org": {
            "id": org.id, "name": org.name, "slug": org.slug,
            "plan": org.plan, "role": member.role,
        }
    }

def _seed_workspace(org: Organisation, db: Session):
    project = Project(org_id=org.id, name="Default Project")
    db.add(project)
    db.flush()
    for env_name, display, color, protected, threshold in [
        ("production", "Production", "#00e676", True, 7.0),
        ("staging", "Staging", "#ff9800", True, 6.0),
        ("development", "Development", "#448aff", False, 0.0),
    ]:
        db.add(Environment(
            project_id=project.id, name=env_name, display_name=display,
            color=color, is_protected=protected, eval_pass_threshold=threshold
        ))

@router.post("/register")
async def register(body: RegisterIn, db: Session = Depends(get_db)):
    # Single-user mode: check if any user exists
    if db.query(User).count() > 0:
        raise HTTPException(
            status_code=403, 
            detail="Registration is locked once the first user is created."
        )
    
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email, hashed_pw=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    db.flush()
    # Auto-generate the primary workspace (aligned with Organization ID)
    org_name = "PromptMatrix"
    org = Organisation(name=org_name, slug=_unique_slug("promptmatrix", db), plan="free")
    db.add(org)
    db.flush()
    member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
    db.add(member)
    db.flush()
    _seed_workspace(org, db)
    db.add(AuditLog(
        org_id=org.id, actor_id=user.id, actor_email=user.email,
        action="org.created", resource_type="org", resource_id=org.id,
        extra={"mode": "local"}
    ))
    db.commit()
    return _build_auth_response(user, member, org)

@router.post("/login")
async def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    member = db.query(OrgMember).filter(OrgMember.user_id == user.id).first()
    if not member:
        raise HTTPException(status_code=403, detail="No organisation found for this user")
    org = db.query(Organisation).filter(Organisation.id == member.org_id).first()
    db.add(AuditLog(
        org_id=org.id, actor_id=user.id, actor_email=user.email,
        action="auth.login", resource_type="user", resource_id=user.id
    ))
    db.commit()
    return _build_auth_response(user, member, org)

@router.post("/refresh")
async def refresh_token(body: RefreshIn, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    user_id = payload.get("sub")
    org_id = payload.get("org")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {
        "access_token": create_access_token(user_id, org_id),
        "refresh_token": create_refresh_token(user_id, org_id),
        "token_type": "bearer",
    }

@router.get("/me")
async def me(auth=Depends(get_current_user_and_org), db: Session = Depends(get_db)):
    user, member = auth
    if not member:
        return {"user": {"id": user.id, "email": user.email, "full_name": user.full_name}}
    org = db.query(Organisation).filter(Organisation.id == member.org_id).first()
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "active_org": {
            "id": org.id, "name": org.name, "slug": org.slug,
            "plan": org.plan, "role": member.role
        }
    }
