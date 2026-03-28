"""Add check constraints

Revision ID: 8629bc78c047
Revises: 0001
Create Date: 2026-03-28 15:17:52.498639

Notes:
  This migration only adds the integrity_hash column to audit_logs.
  The fk_prompt_live_version FK was already created in migration 0001.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '8629bc78c047'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_logs', sa.Column('integrity_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_logs', 'integrity_hash')
