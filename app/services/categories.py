"""Category management on top of the system presets."""

import re
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import Category
from app.db.repositories.categories import CategoriesRepository
from app.domain.errors import (
    CategoryInUseError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

CODE_PATTERN = re.compile(r"^[a-z0-9_]{2,32}$")
TITLE_MAX_LENGTH = 64


class CategoriesService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._categories = CategoriesRepository(session)

    async def list_for_user(self, user_id: int) -> Sequence[Category]:
        return await self._categories.list_available(user_id)

    async def get_for_user(self, user_id: int, category_id: int) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None or category.archived_at is not None:
            raise NotFoundError(f"category {category_id} not found")
        if category.owner_id is not None and category.owner_id != user_id:
            raise PermissionDeniedError(f"category {category_id} belongs to another user")
        return category

    async def create(self, user_id: int, code: str, title: str, emoji: str) -> Category:
        if not CODE_PATTERN.match(code):
            raise ValidationError(f"invalid category code: {code}")
        if not 1 <= len(title) <= TITLE_MAX_LENGTH:
            raise ValidationError("category title must be 1..64 characters")
        if await self._categories.get_by_code(code, owner_id=user_id) is not None:
            raise ValidationError(f"category {code} already exists")

        category = await self._categories.add(
            Category(owner_id=user_id, code=code, title=title, emoji=emoji, is_system=False)
        )
        await self._session.commit()
        return category

    async def rename(self, user_id: int, category_id: int, title: str) -> Category:
        category = await self._own_category(user_id, category_id)
        if not 1 <= len(title) <= TITLE_MAX_LENGTH:
            raise ValidationError("category title must be 1..64 characters")
        category.title = title
        await self._session.commit()
        return category

    async def archive(self, user_id: int, category_id: int) -> Category:
        category = await self._own_category(user_id, category_id)
        if await self._categories.count_active_reminders(category_id):
            raise CategoryInUseError("category still has non-archived reminders")
        category.archived_at = self._clock.now()
        await self._session.commit()
        return category

    async def _own_category(self, user_id: int, category_id: int) -> Category:
        category = await self.get_for_user(user_id, category_id)
        if category.owner_id is None:
            raise PermissionDeniedError("system categories are read-only")
        return category
