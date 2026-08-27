"""Occurrence queries. The occurrences table is the queue."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Delivery, Occurrence
from app.domain.contracts import TERMINAL_DELIVERY_STATUSES, OccurrenceStatus


class OccurrencesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, occurrence_id: int) -> Occurrence | None:
        return await self._session.get(Occurrence, occurrence_id)

    async def insert_missing(self, rows: list[dict[str, object]]) -> int:
        """Insert planned occurrences, skipping the ones already materialised.

        The (reminder_id, scheduled_for) unique key makes a repeated planner run
        a no-op.
        """
        if not rows:
            return 0
        stmt = (
            pg_insert(Occurrence)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["reminder_id", "scheduled_for"])
            .returning(Occurrence.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())

    async def list_for_schedule(
        self, reminder_id: int, scheduled_for: Sequence[datetime]
    ) -> Sequence[Occurrence]:
        if not scheduled_for:
            return []
        stmt = sa.select(Occurrence).where(
            Occurrence.reminder_id == reminder_id,
            Occurrence.scheduled_for.in_(scheduled_for),
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def count_for_reminder(self, reminder_id: int) -> int:
        stmt = sa.select(sa.func.count()).where(Occurrence.reminder_id == reminder_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def set_status(self, occurrence_id: int, status: OccurrenceStatus) -> None:
        stmt = sa.update(Occurrence).where(Occurrence.id == occurrence_id).values(status=status)
        await self._session.execute(stmt)

    async def bump_repeats(self, occurrence_id: int) -> None:
        stmt = (
            sa.update(Occurrence)
            .where(Occurrence.id == occurrence_id)
            .values(repeats_sent=Occurrence.repeats_sent + 1)
        )
        await self._session.execute(stmt)

    async def all_deliveries_terminal(self, occurrence_id: int) -> bool:
        stmt = sa.select(sa.func.count()).where(
            Delivery.occurrence_id == occurrence_id,
            Delivery.status.not_in(TERMINAL_DELIVERY_STATUSES),
        )
        return int((await self._session.execute(stmt)).scalar_one()) == 0

    async def list_expired(self, now: datetime, limit: int) -> Sequence[Occurrence]:
        stmt = (
            sa.select(Occurrence)
            .where(
                Occurrence.expires_at < now,
                Occurrence.status.not_in(
                    [
                        OccurrenceStatus.DONE,
                        OccurrenceStatus.SKIPPED,
                        OccurrenceStatus.EXPIRED,
                        OccurrenceStatus.FAILED,
                    ]
                ),
            )
            .order_by(Occurrence.expires_at)
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()
