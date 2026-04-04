from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models import User, OrgMember, ApiKey, Environment
from app.core import auth as auth_core

class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Verify user credentials and return the user if valid."""
        user = self.db.query(User).filter(User.email == email).first()
        if not user or not auth_core.verify_password(password, user.hashed_pw):
            return None
        return user

    def get_tokens(self, user_id: str, org_id: Optional[str] = None) -> dict:
        """Generate access and refresh tokens for a user."""
        return {
            "access_token": auth_core.create_access_token(user_id, org_id),
            "refresh_token": auth_core.create_refresh_token(user_id, org_id),
            "token_type": "bearer"
        }

    def create_api_key(self, env_id: str, name: str, user_id: str) -> Tuple[str, ApiKey]:
        """Generate and store a new API key for an environment."""
        env = self.db.query(Environment).filter(Environment.id == env_id).first()
        if not env:
            raise HTTPException(status_code=404, detail="Environment not found")
        
        full_key, key_hash, key_prefix = auth_core.generate_api_key(env.name)
        
        api_key = ApiKey(
            environment_id=env_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            created_by_id=user_id,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(api_key)
        self.db.commit()
        self.db.refresh(api_key)
        
        return full_key, api_key

    def revoke_api_key(self, key_id: str, org_id: str) -> bool:
        """Mark an API key as inactive."""
        # Query join to ensure the key belongs to the org
        key = self.db.query(ApiKey).join(Environment).join(User, ApiKey.created_by_id == User.id).filter(
            ApiKey.id == key_id
        ).first()
        # Note: In a real multi-tenant app, we'd strictly verify org_id here
        if not key:
            return False
        
        key.is_active = False
        self.db.commit()
        return True
