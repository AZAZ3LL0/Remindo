"""Delivery queue access, including the SKIP LOCKED claim."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Delivery, DeliveryAction, Occurrence, Reminder, User
from app.domain.contracts import ActionKind, DeliveryStatus


class DeliveriesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, delivery_id: int) -> Delivery | None:
        return await self._session.get(Delivery, delivery_id)

    async def get_for_update(self, delivery_id: int) -> Delivery | None:
        """Row lock for the reaction path, so a double tap serialises."""
        stmt = sa.select(Delivery).where(Delivery.id == delivery_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def insert_missing(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        stmt = (
            pg_insert(Delivery)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["occurrence_id", "user_id"])
            .returning(Delivery.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())

    async def claim_due(self, now: datetime, lock_for: timedelta, batch: int) -> Sequence[Delivery]:
        """Lease a batch of due deliveries. Concurrent workers never collide."""
        due = (
            sa.select(Delivery.id)
            .where(
                Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.SNOOZED]),
                Delivery.next_attempt_at <= now,
                sa.or_(Delivery.locked_until.is_(None), Delivery.locked_until < now),
            )
            .order_by(Delivery.next_attempt_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            sa.update(Delivery)
            .where(Delivery.id.in_(due))
            .values(locked_until=now + lock_for, attempts=Delivery.attempts + 1)
            .returning(Delivery)
            # populate_existing makes RETURNING refresh the identity map, so the
            # claimed rows carry the incremented attempt counter.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def load_send_context(
        self, delivery_ids: Sequence[int]
    ) -> dict[int, tuple[Occurrence, Reminder, Category, User]]:
        """Everything one batch needs to render its messages, in one query.

        The claim hands back a batch, so loading the context row by row would
        cost four round trips per delivery.
        """
        if not delivery_ids:
            return {}
        stmt = (
            sa.select(Delivery.id, Occurrence, Reminder, Category, User)
            .join(Occurrence, Occurrence.id == Delivery.occurrence_id)
            .join(Reminder, Reminder.id == Occurrence.reminder_id)
            .join(Category, Category.id == Reminder.category_id)
            .join(User, User.id == Delivery.user_id)
            .where(Delivery.id.in_(delivery_ids))
        )
        rows = (await self._session.execute(stmt)).all()
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}

    async def update_fields(self, delivery_id: int, **values: Any) -> None:
        stmt = sa.update(Delivery).where(Delivery.id == delivery_id).values(**values)
        await self._session.execute(stmt)

    async def add_action(
        self,
        delivery_id: int,
        user_id: int,
        kind: ActionKind,
        created_at: datetime,
        payload: dict[str, Any] | None = None,
    ) -> DeliveryAction:
        # The moment comes from the service clock, never from the database, so
        # statistics stay consistent with the rest of the domain.
        action = DeliveryAction(
            delivery_id=delivery_id,
            user_id=user_id,
            kind=kind,
            payload=payload or {},
            created_at=created_at,
        )
        self._session.add(action)
        await self._session.flush()
        return action

    async def count_actions(self, delivery_id: int, kind: ActionKind | None = None) -> int:
        stmt = sa.select(sa.func.count()).where(DeliveryAction.delivery_id == delivery_id)
        if kind is not None:
            stmt = stmt.where(DeliveryAction.kind == kind)
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_actions_for_user(
        self, user_id: int, since: datetime, category_id: int | None = None
    ) -> Sequence[DeliveryAction]:
        stmt = (
            sa.select(DeliveryAction)
            .join(Delivery, Delivery.id == DeliveryAction.delivery_id)
            .join(Occurrence, Occurrence.id == Delivery.occurrence_id)
            .join(Reminder, Reminder.id == Occurrence.reminder_id)
            .where(DeliveryAction.user_id == user_id, DeliveryAction.created_at >= since)
        )
        if category_id is not None:
            stmt = stmt.where(Reminder.category_id == category_id)
        return (await self._session.execute(stmt)).scalars().all()

    def _day_query(self, user_id: int, start: datetime, end: datetime) -> sa.Select[Any]:
        """Deliveries addressed to one user inside one local day (tech.md 21.9)."""
        return (
            sa.select(Delivery, Occurrence, Reminder, Category)
            .join(Occurrence, Occurrence.id == Delivery.occurrence_id)
            .join(Reminder, Reminder.id == Occurrence.reminder_id)
            .join(Category, Category.id == Reminder.category_id)
            .where(
                Delivery.user_id == user_id,
                Occurrence.fire_at >= start,
                Occurrence.fire_at < end,
            )
        )

    async def list_for_day(
        self, user_id: int, start: datetime, end: datetime, limit: int, offset: int
    ) -> Sequence[tuple[Delivery, Occurrence, Reminder, Category]]:
        stmt = (
            self._day_query(user_id, start, end)
            .order_by(Occurrence.fire_at, Delivery.id)
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    async def count_for_day(self, user_id: int, start: datetime, end: datetime) -> int:
        stmt = sa.select(sa.func.count()).select_from(
            self._day_query(user_id, start, end).subquery()
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_sent_for_occurrence(self, occurrence_id: int) -> Sequence[Delivery]:
        stmt = sa.select(Delivery).where(
            Delivery.occurrence_id == occurrence_id,
            Delivery.status == DeliveryStatus.SENT,
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_repeat_candidates(
        self, now: datetime, limit: int
    ) -> Sequence[tuple[Delivery, Reminder, Occurrence, User]]:
        """Sent deliveries with no reaction that may be due for an automatic repeat.

        The predicate narrows the batch; the repeat itself is decided in the
        domain, which is why the recipient rides along: quiet hours are theirs.
        """
        stmt = (
            sa.select(Delivery, Reminder, Occurrence, User)
            .join(Occurrence, Occurrence.id == Delivery.occurrence_id)
            .join(Reminder, Reminder.id == Occurrence.reminder_id)
            .join(User, User.id == Delivery.user_id)
            .where(
                Delivery.status == DeliveryStatus.SENT,
                Delivery.reacted_at.is_(None),
                Delivery.sent_at.is_not(None),
                Reminder.repeat_after_minutes.is_not(None),
                Occurrence.repeats_sent < Reminder.max_repeats,
                Occurrence.expires_at > now,
                # type_coerce keeps the sum timezone-aware; without it the
                # driver compares an aware bind against a naive expression.
                sa.type_coerce(
                    Delivery.sent_at
                    + sa.cast(
                        sa.func.concat(Reminder.repeat_after_minutes, " minutes"), sa.Interval
                    ),
                    sa.TIMESTAMP(timezone=True),
                )
                <= now,
            )
            .order_by(Delivery.sent_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    async def release_stale_locks(self, now: datetime) -> int:
        stmt = (
            sa.update(Delivery)
            .where(
                Delivery.locked_until.is_not(None),
                Delivery.locked_until < now,
                Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.SNOOZED]),
            )
            .values(locked_until=None)
            .returning(Delivery.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())
