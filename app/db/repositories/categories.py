"""Category queries."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Reminder
from app.domain.contracts import ReminderStatus


class CategoriesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, category_id: int) -> Category | None:
        return await self._session.get(Category, category_id)

    async def get_by_code(self, code: str, owner_id: int | None = None) -> Category | None:
        owner_clause = (
            Category.owner_id.is_(None) if owner_id is None else Category.owner_id == owner_id
        )
        stmt = sa.select(Category).where(Category.code == code, owner_clause)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_available(self, owner_id: int) -> Sequence[Category]:
        """System presets plus the user's own, active first, stable order."""
        stmt = (
            sa.select(Category)
            .where(
                sa.or_(Category.owner_id.is_(None), Category.owner_id == owner_id),
                Category.archived_at.is_(None),
            )
            .order_by(Category.sort_order, Category.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def add(self, category: Category) -> Category:
        self._session.add(category)
        await self._session.flush()
        return category

    async def count_active_reminders(self, category_id: int) -> int:
        stmt = sa.select(sa.func.count()).where(
            Reminder.category_id == category_id,
            Reminder.status != ReminderStatus.ARCHIVED,
        )
        return int((await self._session.execute(stmt)).scalar_one())
