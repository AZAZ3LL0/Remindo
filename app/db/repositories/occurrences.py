"""Occurrence queries. The occurrences table is the queue."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Delivery, Occurrence
from app.domain.contracts import (
    TERMINAL_DELIVERY_STATUSES,
    DeliveryStatus,
    OccurrenceStatus,
)


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

    async def delete_unsent(self, reminder_id: int) -> int:
        """Drop queued occurrences nothing has gone out for (tech.md 21.3).

        Rows are deleted rather than marked: no delivery happened, so the log
        has nothing to keep, and `skipped` is a reaction of the user's and would
        show up in the statistics as one. Deliveries follow by cascade.

        An occurrence any delivery has left `pending` for is kept: somebody is
        looking at a message with live buttons, and a pause has no business
        taking those away.
        """
        answered = (
            sa.select(Delivery.id)
            .where(
                Delivery.occurrence_id == Occurrence.id,
                Delivery.status != DeliveryStatus.PENDING,
            )
            .exists()
        )
        stmt = (
            sa.delete(Occurrence)
            .where(
                Occurrence.reminder_id == reminder_id,
                Occurrence.status == OccurrenceStatus.PENDING,
                ~answered,
            )
            .returning(Occurrence.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())

    async def next_fire_at(self, reminder_id: int, after: datetime) -> datetime | None:
        stmt = (
            sa.select(Occurrence.fire_at)
            .where(
                Occurrence.reminder_id == reminder_id,
                Occurrence.status == OccurrenceStatus.PENDING,
                Occurrence.fire_at >= after,
            )
            .order_by(Occurrence.fire_at)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

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
