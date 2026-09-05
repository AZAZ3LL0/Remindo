"""Statistics built from the append-only action journal (tech.md 23.1).

The journal is the only source. The queue is not one: a pause and an
unsubscribe delete rows that never went out, so a completion rate computed
from `deliveries` would change retroactively when somebody presses Pause.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.users import UsersRepository
from app.domain.errors import NotFoundError
from app.domain.stats import STATS_HISTORY_DAYS, ActionRecord, StatsSummary, build_summary


class StatsService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._deliveries = DeliveriesRepository(session)
        self._users = UsersRepository(session)

    async def summary(self, user_id: int, category_id: int | None = None) -> StatsSummary:
        return await self.summary_at(user_id, self._clock.now(), category_id)

    async def summary_at(
        self, user_id: int, moment: datetime, category_id: int | None = None
    ) -> StatsSummary:
        """The summary as it stood at `moment`.

        The digest asks for a past moment rather than for `now`: the cycle
        wakes once a minute and quiet hours postpone the send, so a summary
        pinned to the send would report a different week every retry
        (tech.md 23.5).
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")
        return await self.summary_for(user, moment, category_id)

    async def summary_for(
        self, user: User, moment: datetime, category_id: int | None = None
    ) -> StatsSummary:
        """The same summary for a user row already in hand.

        The digest cycle holds one, and re-reading it once per user would cost
        the batch a query it does not need.
        """
        rows = await self._deliveries.list_actions_for_user(
            user.id,
            since=moment - timedelta(days=STATS_HISTORY_DAYS),
            until=moment,
            category_id=category_id,
        )
        records = [
            ActionRecord(happened_at=action.created_at, kind=action.kind, category_id=category)
            for action, category in rows
        ]
        return build_summary(records, ZoneInfo(user.timezone), moment)
