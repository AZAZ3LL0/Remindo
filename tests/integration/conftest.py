"""Helpers for tests that need rows in the queue."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Delivery, Occurrence, Reminder
from tests.conftest import FROZEN_NOW


@pytest_asyncio.fixture
async def occurrence_factory(db_session: AsyncSession) -> Callable[..., Awaitable[Occurrence]]:
    async def _create(
        reminder: Reminder, fire_at: datetime | None = None, **overrides: object
    ) -> Occurrence:
        fire_at = fire_at or FROZEN_NOW
        occurrence = Occurrence(
            **{
                "reminder_id": reminder.id,
                "scheduled_for": fire_at,
                "fire_at": fire_at,
                "expires_at": fire_at + timedelta(hours=3),
                **overrides,
            }
        )
        db_session.add(occurrence)
        await db_session.flush()
        return occurrence

    return _create


@pytest_asyncio.fixture
async def delivery_factory(db_session: AsyncSession) -> Callable[..., Awaitable[Delivery]]:
    async def _create(occurrence: Occurrence, user_id: int, **overrides: object) -> Delivery:
        delivery = Delivery(
            **{
                "occurrence_id": occurrence.id,
                "user_id": user_id,
                "next_attempt_at": occurrence.fire_at,
                **overrides,
            }
        )
        db_session.add(delivery)
        await db_session.flush()
        return delivery

    return _create
