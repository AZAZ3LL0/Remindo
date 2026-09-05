from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReminderInvite(Base):
    """A deep-link invitation to one reminder (tech.md 22.1).

    A row rather than a signature derived from the reminder id: a signed token
    neither expires nor revokes, so a link that once reached a group chat would
    keep working forever.
    """

    __tablename__ = "reminder_invites"
    __table_args__ = (
        sa.UniqueConstraint("token", name="uq_reminder_invites_token"),
        # One live invitation per reminder, so revoking actually revokes: with
        # two live links, taking one back would take nothing back.
        sa.Index(
            "uq_reminder_invites_live",
            "reminder_id",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_by: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )
