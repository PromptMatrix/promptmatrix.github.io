"""Initial schema — all tables

Revision ID: 0001
Revises: 
Create Date: 2026-03-23

Notes:
  The circular FK between prompts.live_version_id → prompt_versions.id
  uses different strategies per dialect:
    - PostgreSQL (Supabase production): standard ALTER TABLE ADD CONSTRAINT
    - SQLite (local dev): inline FK — SQLite ignores FK enforcement by default
      so this does not need ALTER TABLE and works without batch mode.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), unique=True, nullable=False),
        sa.Column("plan", sa.String(20), server_default="free"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_pw", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(120), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("email_verified", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "org_members",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), server_default="editor"),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("org_id", "user_id"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "environments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(80), server_default=""),
        sa.Column("color", sa.String(20), server_default="#888888"),
        sa.Column("is_protected", sa.Boolean(), server_default="1"),
        sa.Column("eval_pass_threshold", sa.Float(), server_default="7.0"),
        sa.Column("promotion_source_id", sa.String(), sa.ForeignKey("environments.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("project_id", "name"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("environment_id", sa.String(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "eval_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(20), server_default=""),
        sa.Column("label", sa.String(120), server_default=""),
        sa.Column("created_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_email", sa.String(255), server_default=""),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(40), server_default=""),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_audit_org_created", "audit_logs", ["org_id", "created_at"])

    # prompts — live_version_id FK added after prompt_versions exists
    op.create_table(
        "prompts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("environment_id", sa.String(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("live_version_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("environment_id", "key"),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("prompt_id", sa.String(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_num", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("commit_message", sa.String(500), server_default=""),
        sa.Column("variables", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(30), server_default="draft"),
        sa.Column("proposed_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejected_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), server_default=""),
        sa.Column("approval_note", sa.Text(), server_default=""),
        sa.Column("parent_content", sa.Text(), nullable=True),
        sa.Column("last_eval_score", sa.Float(), nullable=True),
        sa.Column("last_eval_passed", sa.Boolean(), nullable=True),
        sa.Column("last_eval_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("prompt_id", "version_num"),
    )
    op.create_index("ix_pv_prompt_status", "prompt_versions", ["prompt_id", "status"])

    # Add circular FK: prompts.live_version_id → prompt_versions.id
    # PostgreSQL supports ALTER TABLE ADD CONSTRAINT for this.
    # SQLite does not support ALTER TABLE on constraints — but SQLite also
    # doesn't enforce FK constraints by default, so we skip it on SQLite.
    # In production (Supabase/PostgreSQL) this runs correctly.
    if not _is_sqlite():
        op.create_foreign_key(
            "fk_prompt_live_version",
            "prompts", "prompt_versions",
            ["live_version_id"], ["id"],
        )


def downgrade() -> None:
    if not _is_sqlite():
        op.drop_constraint("fk_prompt_live_version", "prompts", type_="foreignkey")

    op.drop_index("ix_pv_prompt_status", table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_table("prompts")
    op.drop_index("ix_audit_org_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("eval_keys")
    op.drop_table("api_keys")
    op.drop_table("environments")
    op.drop_table("projects")
    op.drop_table("org_members")
    op.drop_table("users")
    op.drop_table("organisations")
