"""Add the weekly digest columns to users

Revision ID: a7e30c15b482
Revises: 9c1f4b7ae520
Create Date: 2026-09-05 22:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7e30c15b482"
down_revision: str | None = "9c1f4b7ae520"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "digest_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("digest_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "digest_sent_at")
    op.drop_column("users", "digest_enabled")
