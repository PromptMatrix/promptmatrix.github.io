"""
Models
=======
Hierarchy: Organisation → Project → Environment → Prompt → PromptVersion

The circular FK between Prompt.live_version_id ↔ PromptVersion.prompt_id
is resolved with use_alter=True on the live_version_id FK — SQLAlchemy creates
the FK as a separate ALTER TABLE after both tables exist.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Integer, Float,
    ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.utcnow()


# ── Org / Auth ────────────────────────────────────────────────────

class Organisation(Base):
    __tablename__ = "organisations"

    id         = Column(String, primary_key=True, default=_uuid)
    name       = Column(String(120), nullable=False)
    slug       = Column(String(80), unique=True, nullable=False)
    plan       = Column(String(20), default="free")   # free | founding | enterprise
    created_at = Column(DateTime, default=_now)

    members  = relationship("OrgMember", back_populates="org", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="org", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True, default=_uuid)
    email         = Column(String(255), unique=True, nullable=False)
    hashed_pw     = Column(String, nullable=False)
    full_name     = Column(String(120), default="")
    is_active     = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=_now)

    memberships = relationship("OrgMember", back_populates="user")


class OrgMember(Base):
    __tablename__ = "org_members"

    id         = Column(String, primary_key=True, default=_uuid)
    org_id     = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role       = Column(String(20), default="editor")   # viewer|editor|engineer|admin|owner
    joined_at  = Column(DateTime, default=_now)

    org  = relationship("Organisation", back_populates="members")
    user = relationship("User", back_populates="memberships")

    __table_args__ = (UniqueConstraint("org_id", "user_id"),)


# ── Project / Environment ─────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id         = Column(String, primary_key=True, default=_uuid)
    org_id     = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name       = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=_now)

    org          = relationship("Organisation", back_populates="projects")
    environments = relationship("Environment", back_populates="project", cascade="all, delete-orphan")


class Environment(Base):
    __tablename__ = "environments"

    id                   = Column(String, primary_key=True, default=_uuid)
    project_id           = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name                 = Column(String(40), nullable=False)     # production | staging | development
    display_name         = Column(String(80), default="")
    color                = Column(String(20), default="#888888")   # UI accent color
    is_protected         = Column(Boolean, default=True)           # require approval before live
    eval_pass_threshold  = Column(Float, default=7.0)
    promotion_source_id  = Column(String, ForeignKey("environments.id"), nullable=True)
    created_at           = Column(DateTime, default=_now)

    project = relationship("Project", back_populates="environments")
    prompts = relationship("Prompt", back_populates="environment", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="environment", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "name"),)


# ── Prompt / Version ──────────────────────────────────────────────

class Prompt(Base):
    __tablename__ = "prompts"

    id              = Column(String, primary_key=True, default=_uuid)
    environment_id  = Column(String, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False)
    key             = Column(String(200), nullable=False)
    description     = Column(Text, default="")
    tags            = Column(JSON, default=list)
    created_at      = Column(DateTime, default=_now)
    updated_at      = Column(DateTime, default=_now, onupdate=_now)

    # Circular FK: Prompt.live_version_id → PromptVersion.id
    # use_alter=True tells SQLAlchemy to add this FK as a separate ALTER TABLE
    # after both tables have been created — avoids circular dependency.
    live_version_id = Column(
        String,
        ForeignKey("prompt_versions.id", use_alter=True, name="fk_prompt_live_version"),
        nullable=True
    )

    environment  = relationship("Environment", back_populates="prompts")
    versions     = relationship(
        "PromptVersion",
        back_populates="prompt",
        foreign_keys="PromptVersion.prompt_id",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version_num"
    )
    live_version = relationship(
        "PromptVersion",
        foreign_keys=[live_version_id],
        post_update=True  # required for circular FK
    )

    __table_args__ = (UniqueConstraint("environment_id", "key"),)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id             = Column(String, primary_key=True, default=_uuid)
    prompt_id      = Column(String, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    version_num    = Column(Integer, nullable=False)
    content        = Column(Text, nullable=False)
    commit_message = Column(String(500), default="")
    variables      = Column(JSON, default=dict)
    status         = Column(String(30), default="draft")
    # draft | pending_review | approved | rejected | archived

    # Who proposed and who approved
    proposed_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    approved_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    rejected_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, default="")
    approval_note    = Column(Text, default="")

    # Snapshot of parent content at time of proposal (for diff view)
    parent_content = Column(Text, nullable=True)

    # Eval
    last_eval_score   = Column(Float, nullable=True)
    last_eval_passed  = Column(Boolean, nullable=True)
    last_eval_at      = Column(DateTime, nullable=True)

    created_at  = Column(DateTime, default=_now)
    approved_at = Column(DateTime, nullable=True)

    prompt      = relationship("Prompt", back_populates="versions", foreign_keys=[prompt_id])
    proposed_by = relationship("User", foreign_keys=[proposed_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    rejected_by = relationship("User", foreign_keys=[rejected_by_id])

    __table_args__ = (
        UniqueConstraint("prompt_id", "version_num"),
        Index("ix_pv_prompt_status", "prompt_id", "status"),
    )


# ── API Keys ──────────────────────────────────────────────────────

class ApiKey(Base):
    __tablename__ = "api_keys"

    id             = Column(String, primary_key=True, default=_uuid)
    environment_id = Column(String, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False)
    name           = Column(String(120), nullable=False)
    key_hash       = Column(String(64), unique=True, nullable=False)
    key_prefix     = Column(String(20), nullable=False)   # shown in UI, e.g. "pm_live_xxxx"
    is_active      = Column(Boolean, default=True)
    created_by_id  = Column(String, ForeignKey("users.id"), nullable=True)
    expires_at     = Column(DateTime, nullable=True)
    last_used_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=_now)

    environment = relationship("Environment", back_populates="api_keys")
    created_by  = relationship("User", foreign_keys=[created_by_id])


# ── Eval Team Keys ────────────────────────────────────────────────

class EvalKey(Base):
    __tablename__ = "eval_keys"

    id             = Column(String, primary_key=True, default=_uuid)
    org_id         = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    provider       = Column(String(40), nullable=False)   # anthropic|openai|google|groq|mistral
    encrypted_key  = Column(Text, nullable=False)          # AES-256-GCM encrypted
    key_hint       = Column(String(20), default="")        # last 4 chars for UI display
    label          = Column(String(120), default="")
    created_by_id  = Column(String, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime, default=_now)


# ── Audit Log ─────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id            = Column(String, primary_key=True, default=_uuid)
    org_id        = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    actor_id      = Column(String, ForeignKey("users.id"), nullable=True)
    actor_email   = Column(String(255), default="")     # denormalised for query performance
    action        = Column(String(80), nullable=False)
    resource_type = Column(String(40), default="")
    resource_id   = Column(String, nullable=True)
    extra         = Column(JSON, default=dict)          # 'metadata' is reserved in SQLAlchemy
    created_at    = Column(DateTime, default=_now)

    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
    )
