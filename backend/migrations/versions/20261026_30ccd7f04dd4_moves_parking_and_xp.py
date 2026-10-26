"""Moves of every kind, why a company is parked, and XP on the history

Revision ID: 30ccd7f04dd4
Revises: bda7f7d95d96
Create Date: 2026-10-26 16:10:15.703543
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '30ccd7f04dd4'
down_revision: str | None = 'bda7f7d95d96'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('activity', sa.Column('xp', sa.Integer(), server_default='0', nullable=False))
    op.add_column('activity', sa.Column('tag', sa.String(length=40), nullable=True))
    op.create_index('ix_activity_company_tag', 'activity', ['company_id', 'tag'], unique=False)
    op.add_column('companies', sa.Column('parked_why', sa.Enum('stale_role', 'not_a_fit', 'skipped_apply', 'manual', name='parkedwhy', native_enum=False, length=24), nullable=True))
    op.add_column('companies', sa.Column('parked_reason', sa.Text(), nullable=True))
    op.add_column('companies', sa.Column('cant_apply', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('moves', sa.Column('skip_reason', sa.String(length=200), nullable=True))
    op.create_index('uq_moves_reach_person', 'moves', ['person_id'], unique=True, postgresql_where=sa.text("type = 'reach'"))
    op.add_column('people', sa.Column('emailed_at', sa.Date(), nullable=True))
    op.add_column('people', sa.Column('ab_variant', sa.String(length=1), nullable=True))


def downgrade() -> None:
    op.drop_column('people', 'ab_variant')
    op.drop_column('people', 'emailed_at')
    op.drop_index('uq_moves_reach_person', table_name='moves', postgresql_where=sa.text("type = 'reach'"))
    op.drop_column('moves', 'skip_reason')
    op.drop_column('companies', 'cant_apply')
    op.drop_column('companies', 'parked_reason')
    op.drop_column('companies', 'parked_why')
    op.drop_index('ix_activity_company_tag', table_name='activity')
    op.drop_column('activity', 'tag')
    op.drop_column('activity', 'xp')
