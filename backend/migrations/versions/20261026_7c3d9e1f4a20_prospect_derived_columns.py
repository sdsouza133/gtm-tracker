"""Prospects keep their stage, effective day, first touch, next follow-up and XP in columns, so lists page in SQL

Revision ID: 7c3d9e1f4a20
Revises: 5b1e0c2a9d41
Create Date: 2026-10-26 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.services import fractional

revision: str = '7c3d9e1f4a20'
down_revision: str | None = '5b1e0c2a9d41'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ('stage', 'effective_day', 'first_touch', 'follow_up_due')


def upgrade() -> None:
    op.add_column('prospects', sa.Column('stage', sa.String(length=12), nullable=True))
    op.add_column('prospects', sa.Column('effective_day', sa.Date(), nullable=True))
    op.add_column('prospects', sa.Column('first_touch', sa.Date(), nullable=True))
    op.add_column('prospects', sa.Column('follow_up_due', sa.Date(), nullable=True))
    op.add_column('prospects', sa.Column('xp', sa.Integer(), nullable=True))
    table = sa.table(
        'prospects',
        sa.column('id', sa.String()),
        sa.column('day', sa.Date()),
        sa.column('mine', sa.JSON()),
        sa.column('stage', sa.String()),
        sa.column('effective_day', sa.Date()),
        sa.column('first_touch', sa.Date()),
        sa.column('follow_up_due', sa.Date()),
        sa.column('xp', sa.Integer()),
    )
    bind = op.get_bind()
    for pid, day, mine in bind.execute(sa.select(table.c.id, table.c.day, table.c.mine)).all():
        mine = mine or {}
        follow = fractional.next_follow_up(mine)
        bind.execute(
            table.update()
            .where(table.c.id == pid)
            .values(
                stage=fractional.stage(mine).value,
                effective_day=fractional.effective_day(day, mine),
                first_touch=fractional.first_touch(mine),
                follow_up_due=follow.due if follow else None,
                xp=fractional.xp(mine),
            )
        )
    op.alter_column('prospects', 'stage', nullable=False)
    op.alter_column('prospects', 'effective_day', nullable=False)
    op.alter_column('prospects', 'xp', nullable=False)
    for column in COLUMNS:
        op.create_index(op.f(f'ix_prospects_{column}'), 'prospects', [column], unique=False)


def downgrade() -> None:
    for column in COLUMNS:
        op.drop_index(op.f(f'ix_prospects_{column}'), table_name='prospects')
    for column in (*COLUMNS, 'xp'):
        op.drop_column('prospects', column)
