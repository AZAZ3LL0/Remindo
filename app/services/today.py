"""What one user has on their plate today (tech.md 21.9)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.deliveries import DeliveriesRepository
from app.domain.contracts import DeliveryStatus
from app.domain.reminders import local_day_bounds, local_today


@dataclass(frozen=True, slots=True)
class TodayEntry:
    """One delivery of the day, flattened for the renderer."""

    fire_at: datetime
    emoji: str
    title: str
    status: DeliveryStatus


class TodayService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._clock = clock
        self._deliveries = DeliveriesRepository(session)

    async def list_for_user(
        self, user: User, page: int, page_size: int
    ) -> tuple[Sequence[TodayEntry], int]:
        """The user's day, in their own timezone.

        Deliveries, not occurrences: a shared reminder has several recipients
        and each of them has their own day (tech.md 21.9). Until S10 the owner
        is the only recipient, so the difference does not show yet.
        """
        tz = ZoneInfo(user.timezone)
        start, end = local_day_bounds(local_today(self._clock.now(), tz), tz)

        rows = await self._deliveries.list_for_day(
            user.id, start, end, limit=page_size, offset=page * page_size
        )
        total = await self._deliveries.count_for_day(user.id, start, end)
        entries = [
            TodayEntry(
                fire_at=occurrence.fire_at,
                emoji=category.emoji,
                title=reminder.title,
                status=delivery.status,
            )
            for delivery, occurrence, reminder, category in rows
        ]
        return entries, total
