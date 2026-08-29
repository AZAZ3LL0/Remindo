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

    async def list_owned(self, owner_id: int, *, active_only: bool = True) -> Sequence[Category]:
        """Only what the user may edit: the presets stay out."""
        stmt = sa.select(Category).where(Category.owner_id == owner_id)
        if active_only:
            stmt = stmt.where(Category.archived_at.is_(None))
        return (await self._session.execute(stmt.order_by(Category.id))).scalars().all()

    async def list_codes(self, owner_id: int) -> set[str]:
        """Every code the owner occupies, archived ones included.

        An archived category keeps its row and its code, so a new category
        must not reuse it: the partial unique index counts archived rows too.
        """
        stmt = sa.select(Category.code).where(Category.owner_id == owner_id)
        return set((await self._session.execute(stmt)).scalars().all())

    async def add(self, category: Category) -> Category:
        self._session.add(category)
        await self._session.flush()
        return category

    async def count_active_reminders_by_category(
        self, category_ids: Sequence[int]
    ) -> dict[int, int]:
        """Non-archived reminders per category, for the list and the card."""
        if not category_ids:
            return {}
        stmt = (
            sa.select(Reminder.category_id, sa.func.count())
            .where(
                Reminder.category_id.in_(category_ids),
                Reminder.status != ReminderStatus.ARCHIVED,
            )
            .group_by(Reminder.category_id)
        )
        return {row[0]: int(row[1]) for row in (await self._session.execute(stmt)).all()}

    async def count_active_reminders(self, category_id: int) -> int:
        counts = await self.count_active_reminders_by_category([category_id])
        return counts.get(category_id, 0)
