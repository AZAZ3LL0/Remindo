"""User queries. No transaction control here."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_tg_id(self, tg_user_id: int) -> User | None:
        stmt = sa.select(User).where(User.tg_user_id == tg_user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def list_by_ids(self, user_ids: Sequence[int]) -> Sequence[User]:
        if not user_ids:
            return []
        stmt = sa.select(User).where(User.id.in_(user_ids))
        return (await self._session.execute(stmt)).scalars().all()

    async def mark_blocked(self, user_id: int, blocked: bool) -> None:
        stmt = sa.update(User).where(User.id == user_id).values(is_blocked=blocked)
        await self._session.execute(stmt)
