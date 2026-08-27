"""Statistics built from the append-only action journal."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.users import UsersRepository
from app.domain.errors import NotFoundError
from app.domain.stats import ActionRecord, StatsSummary, build_summary

#: The longest window the summary reports over.
HISTORY_DAYS = 30


class StatsService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._deliveries = DeliveriesRepository(session)
        self._users = UsersRepository(session)

    async def summary(self, user_id: int, category_id: int | None = None) -> StatsSummary:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")

        now = self._clock.now()
        actions = await self._deliveries.list_actions_for_user(
            user_id, since=now - timedelta(days=HISTORY_DAYS), category_id=category_id
        )
        records = [
            ActionRecord(happened_at=action.created_at, kind=action.kind) for action in actions
        ]
        return build_summary(records, ZoneInfo(user.timezone), now)
