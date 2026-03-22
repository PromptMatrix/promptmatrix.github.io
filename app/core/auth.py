"""
Core Auth
=========
JWT token creation/validation
API key generation + hashing
Password hashing
AES-256-GCM encryption for stored LLM keys
"""

import secrets
import hashlib
import base64
import os
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

settings = get_settings()

# ── Password hashing ─────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ──────────────────────────────────────────────────────────
def create_access_token(user_id: str, org_id: Optional[str] = None) -> str:
    payload = {
        "sub": user_id,
        "org": org_id,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str, org_id: Optional[str] = None) -> str:
    """org_id included so token refresh preserves org context."""
    payload = {
        "sub": user_id,
        "org": org_id,
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
        "iat": datetime.utcnow(),
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


# ── API Key generation ───────────────────────────────────────────
def generate_api_key(env_name: str) -> tuple[str, str, str]:
    """
    Returns (full_key, key_hash, key_prefix)
    full_key   — shown ONCE to the user, never stored
    key_hash   — SHA-256 hash stored in DB for lookups
    key_prefix — first 16 chars, stored for UI display ("pm_live_xxxx")
    """
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


# ── FastAPI dependencies ─────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.models import User
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.models import User, OrgMember
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


# ── Role checks ──────────────────────────────────────────────────
ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "engineer": 2, "admin": 3, "owner": 4}


def require_role(member, min_role: str):
    if not member:
        raise HTTPException(status_code=403, detail="No org context")
    if ROLE_HIERARCHY.get(member.role, 0) < ROLE_HIERARCHY.get(min_role, 99):
        raise HTTPException(
            status_code=403,
            detail=f"Requires '{min_role}' or higher. You are '{member.role}'."
        )


# ── AES-256-GCM encryption for stored LLM keys ──────────────────
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False


def _derive_encryption_key() -> bytes:
    """
    Use ENCRYPTION_KEY if set (recommended in production).
    Falls back to JWT secret only in development.
    These two secrets should NEVER be the same value — rotating
    JWT_SECRET_KEY must not break stored LLM keys.
    """
    key_material = settings.encryption_key or settings.jwt_secret_key
    return hashlib.sha256(key_material.encode()).digest()


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt a team LLM key. Returns base64-encoded nonce+ciphertext."""
    if not _CRYPTO_OK:
        raise RuntimeError(
            "cryptography package is required for LLM key encryption. "
            "Run: pip install cryptography"
        )
    key = _derive_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt a stored LLM key. Only called in server memory during eval runs."""
    if not _CRYPTO_OK:
        raise RuntimeError("cryptography package is required")
    key = _derive_encryption_key()
    aesgcm = AESGCM(key)
    data = base64.b64decode(ciphertext.encode())
    nonce, ct = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()
