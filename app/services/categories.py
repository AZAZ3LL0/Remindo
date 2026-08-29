"""Category management on top of the system presets."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import Category
from app.db.repositories.categories import CategoriesRepository
from app.domain.categories import (
    next_free_code,
    normalize_category_title,
    normalize_emoji,
    slugify_code,
)
from app.domain.errors import (
    CategoryExistsError,
    CategoryInUseError,
    NotFoundError,
    PermissionDeniedError,
)


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """`applied` is false when the category was already in the archive."""

    applied: bool
    category: Category


class CategoriesService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._categories = CategoriesRepository(session)

    async def list_for_user(self, user_id: int) -> Sequence[Category]:
        return await self._categories.list_available(user_id)

    async def counts_for(self, categories: Sequence[Category]) -> dict[int, int]:
        """Live reminders per category, so a card can explain a refusal."""
        return await self._categories.count_active_reminders_by_category(
            [category.id for category in categories]
        )

    async def get_for_user(self, user_id: int, category_id: int) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None or category.archived_at is not None:
            raise NotFoundError(f"category {category_id} not found")
        if category.owner_id is not None and category.owner_id != user_id:
            raise PermissionDeniedError(f"category {category_id} belongs to another user")
        return category

    async def create(self, user_id: int, title: str, emoji: str) -> Category:
        """Create an own category. The code is derived, never typed."""
        clean_title = normalize_category_title(title)
        clean_emoji = normalize_emoji(emoji)
        await self._reject_duplicate(user_id, clean_title)

        code = next_free_code(slugify_code(clean_title), await self._categories.list_codes(user_id))
        category = await self._categories.add(
            Category(
                owner_id=user_id,
                code=code,
                title=clean_title,
                emoji=clean_emoji,
                is_system=False,
            )
        )
        await self._session.commit()
        return category

    async def rename(self, user_id: int, category_id: int, title: str) -> Category:
        """Rename an own category. The code stays: it is an identity, not a label."""
        category = await self._own_category(user_id, category_id)
        clean_title = normalize_category_title(title)
        await self._reject_duplicate(user_id, clean_title, exclude_id=category.id)
        category.title = clean_title
        await self._session.commit()
        return category

    async def archive(self, user_id: int, category_id: int) -> ArchiveResult:
        """Hide an own category. Archiving twice is a no-op, not an error."""
        category = await self._own_category(user_id, category_id, allow_archived=True)
        if category.archived_at is not None:
            return ArchiveResult(applied=False, category=category)
        if await self._categories.count_active_reminders(category_id):
            raise CategoryInUseError("category still has non-archived reminders")
        category.archived_at = self._clock.now()
        await self._session.commit()
        return ArchiveResult(applied=True, category=category)

    async def _reject_duplicate(
        self, user_id: int, title: str, exclude_id: int | None = None
    ) -> None:
        """Two categories under one title differ only by an invisible code."""
        for existing in await self._categories.list_owned(user_id):
            if existing.id != exclude_id and existing.title.casefold() == title.casefold():
                raise CategoryExistsError(f"category {title!r} already exists")

    async def _own_category(
        self, user_id: int, category_id: int, *, allow_archived: bool = False
    ) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None or (category.archived_at is not None and not allow_archived):
            raise NotFoundError(f"category {category_id} not found")
        if category.owner_id is None:
            raise PermissionDeniedError("system categories are read-only")
        if category.owner_id != user_id:
            raise PermissionDeniedError(f"category {category_id} belongs to another user")
        return category
