"""Add reminder_invites: deep-link invitations to a shared reminder

Revision ID: 9c1f4b7ae520
Revises: 2220d8c847bd
Create Date: 2026-09-05 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c1f4b7ae520"
down_revision: str | None = "2220d8c847bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminder_invites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reminder_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reminder_id"],
            ["reminders.id"],
            name=op.f("fk_reminder_invites_reminder_id_reminders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_reminder_invites_created_by_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_invites")),
        sa.UniqueConstraint("token", name="uq_reminder_invites_token"),
    )
    op.create_index(
        "uq_reminder_invites_live",
        "reminder_invites",
        ["reminder_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_reminder_invites_live",
        table_name="reminder_invites",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("reminder_invites")
