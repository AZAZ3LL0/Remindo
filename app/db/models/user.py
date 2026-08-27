from datetime import datetime, time

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint(
            "(quiet_start IS NULL) = (quiet_end IS NULL)",
            name="quiet_hours_both_or_none",
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True)
    tg_chat_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    first_name: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="")
    language: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="ru")
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="Europe/Moscow")
    quiet_start: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    quiet_end: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    onboarded_at: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
