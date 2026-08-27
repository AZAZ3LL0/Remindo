from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        sa.Index(
            "uq_categories_owner_id_code",
            "owner_id",
            "code",
            unique=True,
            postgresql_where=sa.text("owner_id IS NOT NULL"),
        ),
        sa.Index(
            "uq_categories_code_system",
            "code",
            unique=True,
            postgresql_where=sa.text("owner_id IS NULL"),
        ),
        sa.Index(
            "ix_categories_owner_id_active",
            "owner_id",
            postgresql_where=sa.text("archived_at IS NULL"),
        ),
        sa.CheckConstraint("code ~ '^[a-z0-9_]{2,32}$'", name="code_is_slug"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    emoji: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="\U0001f514")
    is_system: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    sort_order: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default="100")
    archived_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )
