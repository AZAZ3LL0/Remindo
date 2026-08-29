from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import RECIPIENT_ROLE, Base
from app.domain.contracts import RecipientRole


class ReminderRecipient(Base):
    __tablename__ = "reminder_recipients"
    __table_args__ = (
        sa.UniqueConstraint("reminder_id", "user_id", name="uq_reminder_recipients_reminder_user"),
        sa.Index(
            "uq_reminder_recipients_single_owner",
            "reminder_id",
            unique=True,
            postgresql_where=sa.text("role = 'owner'"),
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[RecipientRole] = mapped_column(RECIPIENT_ROLE, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )
