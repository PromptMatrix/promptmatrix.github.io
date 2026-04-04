import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Integer, Float,
    ForeignKey, JSON, UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# ── Org / Auth ────────────────────────────────────────────────────

class Organisation(Base):
    __tablename__ = "organisations"
    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(120), nullable=False)
    slug = Column(String(80), unique=True, nullable=False)
    plan = Column(String(20), default="local")  # local|free|solo|team|scale|enterprise
    plan_seat_limit = Column(Integer, default=1)
    plan_prompt_limit = Column(Integer, default=3)
    plan_rpm_limit = Column(Integer, default=30)
    lemon_order_id = Column(String(100), nullable=True)
    billing_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    members = relationship("OrgMember", back_populates="org", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="org", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False)
    hashed_pw = Column(String, nullable=False)
    full_name = Column(String(120), default="")
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    memberships = relationship("OrgMember", back_populates="user", foreign_keys="OrgMember.user_id")


class OrgMember(Base):
    __tablename__ = "org_members"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), default="editor")  # viewer|editor|engineer|admin|owner
    invited_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    joined_at = Column(DateTime, default=_now)
    org = relationship("Organisation", back_populates="members")
    user = relationship("User", back_populates="memberships", foreign_keys=[user_id])
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)


# ── Project / Environment ─────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=_now)
    org = relationship("Organisation", back_populates="projects")
    environments = relationship("Environment", back_populates="project", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("org_id", "name"),)


class Environment(Base):
    __tablename__ = "environments"
    id = Column(String, primary_key=True, default=_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(40), nullable=False)
    display_name = Column(String(80), default="")
    color = Column(String(20), default="#888888")
    is_protected = Column(Boolean, default=False)
    eval_required = Column(Boolean, default=False)
    eval_pass_threshold = Column(Float, default=7.0)
    promotion_source_id = Column(String, ForeignKey("environments.id"), nullable=True)
    created_at = Column(DateTime, default=_now)
    project = relationship("Project", back_populates="environments")
    prompts = relationship("Prompt", back_populates="environment", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="environment", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("project_id", "name"),)


# ── Prompt / Version ──────────────────────────────────────────────

class Prompt(Base):
    __tablename__ = "prompts"
    id = Column(String, primary_key=True, default=_uuid)
    environment_id = Column(String, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(200), nullable=False)
    description = Column(Text, default="")
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    live_version_id = Column(
        String,
        ForeignKey("prompt_versions.id", use_alter=True, name="fk_prompt_live_version"),
        nullable=True
    )
    environment = relationship("Environment", back_populates="prompts")
    versions = relationship(
        "PromptVersion",
        back_populates="prompt",
        foreign_keys="PromptVersion.prompt_id",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version_num"
    )
    live_version = relationship(
        "PromptVersion",
        foreign_keys=[live_version_id],
        post_update=True
    )
    version = Column(Integer, nullable=False, default=1)  # Optimistic Locking
    __table_args__ = (UniqueConstraint("environment_id", "key"),)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id = Column(String, primary_key=True, default=_uuid)
    prompt_id = Column(String, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    version_num = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    commit_message = Column(String(500), default="")
    variables = Column(JSON, default=dict)
    status = Column(String(30), default="draft") # draft|pending_review|approved|rejected|archived
    target_model = Column(String(100), default="")
    target_provider = Column(String(50), default="")
    proposed_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    approved_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    rejected_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, default="")
    approval_note = Column(Text, default="")
    parent_content = Column(Text, nullable=True)
    override_eval = Column(Boolean, default=False)
    last_eval_score = Column(Float, nullable=True)
    last_eval_passed = Column(Boolean, nullable=True)
    last_eval_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    approved_at = Column(DateTime, nullable=True)

    prompt = relationship("Prompt", back_populates="versions", foreign_keys=[prompt_id])
    proposed_by = relationship("User", foreign_keys=[proposed_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    rejected_by = relationship("User", foreign_keys=[rejected_by_id])

    __table_args__ = (
        UniqueConstraint("prompt_id", "version_num"),
        Index("ix_pv_prompt_status", "prompt_id", "status"),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')",
            name="ck_version_status"
        ),
    )


# ── API Keys ──────────────────────────────────────────────────────

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(String, primary_key=True, default=_uuid)
    environment_id = Column(String, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(120), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    key_prefix = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)
    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
    environment = relationship("Environment", back_populates="api_keys")
    created_by = relationship("User", foreign_keys=[created_by_id])


# ── Eval Team Keys ────────────────────────────────────────────────

class EvalKey(Base):
    __tablename__ = "eval_keys"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(40), nullable=False) # anthropic|openai|google|groq|mistral
    encrypted_key = Column(Text, nullable=False)
    key_hint = Column(String(20), default="")
    label = Column(String(120), default="")
    is_active = Column(Boolean, default=True)
    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)


# ── Eval Results History ──────────────────────────────────────────

class EvalResult(Base):
    __tablename__ = "eval_results"
    id = Column(String, primary_key=True, default=_uuid)
    version_id = Column(String, ForeignKey("prompt_versions.id", ondelete="CASCADE"), nullable=False)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    eval_type = Column(String(20), nullable=False) # rule_based|llm_judge
    provider = Column(String(50), default="")
    model = Column(String(100), default="")
    overall_score = Column(Float, nullable=False)
    criteria = Column(JSON, default=dict)
    strengths = Column(JSON, default=list)
    issues = Column(JSON, default=list)
    suggestions = Column(JSON, default=list)
    test_input = Column(Text, default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    duration_ms = Column(Integer, default=0)
    ran_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    ran_at = Column(DateTime, default=_now)


# ── Promotion Requests ────────────────────────────────────────────

class PromotionRequest(Base):
    __tablename__ = "promotion_requests"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    prompt_id = Column(String, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    source_env_id = Column(String, ForeignKey("environments.id"), nullable=False)
    target_env_id = Column(String, ForeignKey("environments.id"), nullable=False)
    version_num = Column(Integer, nullable=False)
    status = Column(String(20), default="pending") # pending|approved|rejected|executed
    created_by_id = Column(String, ForeignKey("users.id"), nullable=False)
    approved_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_now)
    executed_at = Column(DateTime, nullable=True)

    org = relationship("Organisation")
    prompt = relationship("Prompt")
    source_env = relationship("Environment", foreign_keys=[source_env_id])
    target_env = relationship("Environment", foreign_keys=[target_env_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])


# ── Audit Log ─────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True)
    actor_email = Column(String(255), default="")
    action = Column(String(80), nullable=False)
    resource_type = Column(String(40), default="")
    resource_id = Column(String, nullable=True)
    extra = Column(JSON, default=dict)
    integrity_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now)
    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
    )


# ── Serve Events (Agent Telemetry) ────────────────────────────────

class ServeEvent(Base):
    __tablename__ = "serve_events"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    api_key_id = Column(String, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    prompt_id = Column(String, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False)
    version_id = Column(String, ForeignKey("prompt_versions.id"), nullable=True)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=True)
    outcome = Column(String(20), default="served") # served|feedback_ok|feedback_err
    latency_ms = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    llm_latency_ms = Column(Integer, default=0)
    extra = Column(JSON, default=dict)
    served_at = Column(DateTime, default=_now)


# ── Plan Overrides ────────────────────────────────────────────────

class PlanOverride(Base):
    __tablename__ = "plan_overrides"
    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, unique=True)
    rpm_limit = Column(Integer, nullable=True)
    prompt_limit = Column(Integer, nullable=True)
    seat_limit = Column(Integer, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_now)
