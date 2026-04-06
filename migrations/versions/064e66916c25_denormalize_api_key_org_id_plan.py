"""denormalize_api_key_org_id_plan

Revision ID: 064e66916c25
Revises: 9a0a8f177027
Create Date: 2026-04-06 02:08:26.285867
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = '064e66916c25'
down_revision: Union[str, None] = '9a0a8f177027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns (nullable initially for SQLite compatibility)
    op.add_column('api_keys', sa.Column('org_id', sa.String(), nullable=True))
    op.add_column('api_keys', sa.Column('plan', sa.String(length=30), server_default='local', nullable=True))
    op.create_index(op.f('ix_api_keys_org_id'), 'api_keys', ['org_id'], unique=False)

    # 2. Backfill denormalized data
    # Join: api_keys -> environments -> projects -> organisations
    op.execute(
        """
        UPDATE api_keys
        SET 
            org_id = (
                SELECT o.id 
                FROM organisations o
                JOIN projects p ON p.org_id = o.id
                JOIN environments e ON e.project_id = p.id
                WHERE e.id = api_keys.environment_id
            ),
            plan = (
                SELECT o.plan 
                FROM organisations o
                JOIN projects p ON p.org_id = o.id
                JOIN environments e ON e.project_id = p.id
                WHERE e.id = api_keys.environment_id
            )
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_api_keys_org_id'), table_name='api_keys')
    op.drop_column('api_keys', 'plan')
    op.drop_column('api_keys', 'org_id')
