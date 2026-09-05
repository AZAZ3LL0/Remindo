"""User queries. No transaction control here."""

from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

#: Days a digest mark makes a user uninteresting to the cycle. Consecutive
#: weekly moments are a local week apart, and the shortest local week is a day
#: short of seven, so six is the safe floor for the prefilter above.
DIGEST_PREFILTER_DAYS = 6


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

    async def list_digest_candidates(self, now: datetime, limit: int) -> Sequence[User]:
        """Users the digest cycle should look at (tech.md 23.5).

        The predicate narrows the batch; whether a digest is actually owed is
        decided in the domain, because the weekly moment lives in the user's
        own timezone (tech.md 20.3). Consecutive moments are a local week
        apart, so anybody marked within the last six days cannot be due yet,
        and that is all the query is allowed to conclude.

        Ordered by the oldest mark first, so a batch smaller than the user base
        never starves the same people twice.
        """
        stmt = (
            sa.select(User)
            .where(
                User.onboarded_at.is_not(None),
                User.is_blocked.is_(False),
                User.digest_enabled.is_(True),
                sa.or_(
                    User.digest_sent_at.is_(None),
                    User.digest_sent_at < now - timedelta(days=DIGEST_PREFILTER_DAYS),
                ),
            )
            .order_by(User.digest_sent_at.nulls_first(), User.id)
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def mark_digest_sent(self, user_id: int, moment: datetime) -> None:
        """Record the weekly moment covered, never the instant it went out."""
        stmt = sa.update(User).where(User.id == user_id).values(digest_sent_at=moment)
        await self._session.execute(stmt)
