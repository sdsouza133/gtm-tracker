"""One company per domain, case-insensitively; longer history tags (they can carry a person id)

Revision ID: 5b1e0c2a9d41
Revises: 30ccd7f04dd4
Create Date: 2026-10-26 16:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '5b1e0c2a9d41'
down_revision: str | None = '30ccd7f04dd4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('activity', 'tag', type_=sa.String(length=64), existing_type=sa.String(length=40))
    # A later duplicate keeps its row but loses the domain, so the index can be built; the oldest company keeps it.
    op.execute(
        """
        UPDATE companies SET domain = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (PARTITION BY lower(domain) ORDER BY created_at, id) AS n
                FROM companies WHERE domain IS NOT NULL
            ) ranked WHERE n > 1
        )
        """
    )
    op.create_index(
        'uq_companies_domain',
        'companies',
        [sa.text('lower(domain)')],
        unique=True,
        postgresql_where=sa.text('domain IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_companies_domain', table_name='companies', postgresql_where=sa.text('domain IS NOT NULL'))
    op.execute("UPDATE activity SET tag = left(tag, 40)")
    op.alter_column('activity', 'tag', type_=sa.String(length=40), existing_type=sa.String(length=64))
