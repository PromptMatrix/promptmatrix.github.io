import secrets
import hashlib
import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, Request, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db

settings = get_settings()
def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except ValueError:
        return False

def create_access_token(user_id: str, org_id: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "org": org_id,
        "type": "access",
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def create_refresh_token(user_id: str, org_id: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "org": org_id,
        "type": "refresh",
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

def generate_api_key(env_name: str) -> tuple[str, str, str]:
    prefix_map = {
        "production":  "pm_live_",
        "staging":     "pm_stg_",
        "development": "pm_dev_",
    }
    prefix = prefix_map.get(env_name.lower(), "pm_key_")
    raw = secrets.token_urlsafe(32)
    full_key = f"{prefix}{raw}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:16]
    return full_key, key_hash, key_prefix

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.models import User
    
    # 🕵️ STRONGER DEV BYPASS: Localhost + app_env == 'development'
    if not credentials and settings.app_env == "development":
        client_host = request.client.host if request and request.client else "unknown"
        if client_host in ("127.0.0.1", "::1", "localhost", "unknown"):
            user = db.query(User).first()
            if user: return user
            
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def get_current_user_and_org(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.models import User, OrgMember
    
    # 🕵️ STRONGER DEV BYPASS: Localhost + app_env == 'development'
    if not credentials and settings.app_env == "development":
        client_host = request.client.host if request and request.client else "unknown"
        if client_host in ("127.0.0.1", "::1", "localhost", "unknown"):
            user = db.query(User).first()
            if user:
                member = db.query(OrgMember).filter(OrgMember.user_id == user.id).first()
                if member: return user, member
                
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    org_id  = payload.get("org")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not org_id:
        return user, None
    member = db.query(OrgMember).filter(
        OrgMember.user_id == user_id,
        OrgMember.org_id  == org_id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this organisation")
    return user, member

ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "engineer": 2, "admin": 3, "owner": 4}

def require_role(member, min_role: str):
    if not member:
        raise HTTPException(status_code=403, detail="No org context")
    if ROLE_HIERARCHY.get(member.role, 0) < ROLE_HIERARCHY.get(min_role, 99):
        raise HTTPException(
            status_code=403,
            detail=f"Requires '{min_role}' or higher. You are '{member.role}'."
        )

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False

def _derive_encryption_key() -> bytes:
    key_material = settings.encryption_key or settings.jwt_secret_key
    return hashlib.sha256(key_material.encode()).digest()

def encrypt_api_key(plaintext: str) -> str:
    if not _CRYPTO_OK:
        raise RuntimeError("cryptography package is required")
    key = _derive_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def decrypt_api_key(ciphertext: str) -> str:
    if not _CRYPTO_OK:
        raise RuntimeError("cryptography package is required")
    key = _derive_encryption_key()
    aesgcm = AESGCM(key)
    data = base64.b64decode(ciphertext.encode())
    nonce, ct = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()
