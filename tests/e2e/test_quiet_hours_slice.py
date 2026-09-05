"""Quiet hours and the automatic repeat end to end.

The user silences the night, creates a reminder inside it, and the whole
pipeline honours the silence: the planner shifts the delivery moment, the
dispatcher sends at the end of the silence, the reaper brings it back once when
nobody answers, and expires it when nobody ever does.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest_asyncio
import sqlalchemy as sa

from app.bot.callbacks import CatCb, ReactCb, SetCb, WizCb, pack_wall_time
from app.db.models import Category, Delivery, DeliveryAction, Occurrence, Reminder, User
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.services.dispatching import DispatchingService, ReaperService
from app.services.planning import PlanningService
from tests.e2e.conftest import TG_USER_ID

MOSCOW = ZoneInfo("Europe/Moscow")


@pytest_asyncio.fixture
async def pills_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(owner_id=None, code="pills", title="Таблетки", emoji="💊")
        session.add(category)
        await session.commit()
        return category.id


async def fetch_one(session_factory, model, **filters):
    async with session_factory() as session:
        stmt = sa.select(model)
        for column, value in filters.items():
            stmt = stmt.where(getattr(model, column) == value)
        return (await session.execute(stmt)).scalars().first()


async def count_actions(session_factory, delivery_id: int, kind: ActionKind | None = None) -> int:
    async with session_factory() as session:
        stmt = sa.select(sa.func.count()).where(DeliveryAction.delivery_id == delivery_id)
        if kind is not None:
            stmt = stmt.where(DeliveryAction.kind == kind)
        return int((await session.execute(stmt)).scalar_one())


async def plan(session_factory, clock, settings):
    async with session_factory() as session:
        return await PlanningService(
            session,
            clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()


async def dispatch(session_factory, clock, gateway):
    async with session_factory() as session:
        return await DispatchingService(
            session, clock, gateway, batch_size=10, lock_seconds=60
        ).deliver()


async def sweep(session_factory, clock, gateway):
    async with session_factory() as session:
        return await ReaperService(session, clock, gateway).sweep()


async def test_a_silenced_night_postpones_repeats_and_expires_the_reminder(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, pills_category
):
    # 1. The user picks a timezone and silences the night.
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())
    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="edit").pack())
    await feed.press(WizCb(step="qs", value=pack_wall_time("23:00")).pack())
    await feed.press(WizCb(step="qe", value=pack_wall_time("07:00")).pack())

    user = await fetch_one(session_factory, User, tg_user_id=TG_USER_ID)
    assert (user.quiet_start.hour, user.quiet_end.hour) == (23, 7)

    # 2. A daily reminder lands in the middle of that silence.
    await feed.message("/new")
    await feed.press(CatCb(category_id=pills_category, action="pick").pack())
    await feed.message("Выпить таблетку")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("03:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    reminder = await fetch_one(session_factory, Reminder, owner_id=user.id)
    assert reminder.schedule == {"kind": "daily", "times": ["03:00"], "every_n_days": 1}

    # The repeat delay has no screen until S9 (tech.md 18.7), so it is set here
    # the way editing will set it.
    async with session_factory() as session:
        await session.execute(
            sa.update(Reminder)
            .where(Reminder.id == reminder.id)
            .values(repeat_after_minutes=30, max_repeats=1)
        )
        await session.commit()

    # 3. The planner moves the delivery to the end of the silence.
    assert (await plan(session_factory, fake_clock, settings)).occurrences_created >= 1

    occurrence = await fetch_one(session_factory, Occurrence, reminder_id=reminder.id)
    assert occurrence.scheduled_for.astimezone(MOSCOW).hour == 3
    assert occurrence.fire_at.astimezone(MOSCOW).hour == 7
    assert occurrence.expires_at == occurrence.fire_at + timedelta(
        minutes=settings.occurrence_ttl_minutes
    )

    # 4. Nothing goes out while the night lasts.
    fake_clock.set(datetime(2026, 6, 2, 0, 0, tzinfo=UTC))  # 03:00 local
    assert (await dispatch(session_factory, fake_clock, fake_bot)).sent == 0
    assert fake_bot.sent == []

    # 5. Morning comes and the reminder is delivered.
    fake_clock.set(occurrence.fire_at)
    assert (await dispatch(session_factory, fake_clock, fake_bot)).sent == 1

    delivery = await fetch_one(session_factory, Delivery, occurrence_id=occurrence.id)
    assert delivery.status is DeliveryStatus.SENT
    assert "Выпить таблетку" in fake_bot.sent[0].text

    # 6. Nobody answers, so the reaper queues one repeat and no more.
    fake_clock.set(occurrence.fire_at + timedelta(minutes=30))
    assert (await sweep(session_factory, fake_clock, fake_bot)).repeated == 1
    assert (await dispatch(session_factory, fake_clock, fake_bot)).sent == 1
    assert len(fake_bot.sent) == 2

    fake_clock.set(occurrence.fire_at + timedelta(minutes=70))
    assert (await sweep(session_factory, fake_clock, fake_bot)).repeated == 0

    # 7. The TTL runs out: the occurrence expires and loses its buttons.
    fake_clock.set(occurrence.expires_at + timedelta(minutes=1))
    assert (await sweep(session_factory, fake_clock, fake_bot)).expired == 1

    expired = await fetch_one(session_factory, Occurrence, id=occurrence.id)
    assert expired.status is OccurrenceStatus.EXPIRED
    assert fake_bot.edited[-1][2] is None
    assert await count_actions(session_factory, delivery.id, ActionKind.AUTO_EXPIRE) == 1

    # 8. A button pressed after the fact answers, but changes nothing.
    buttons = [button for row in fake_bot.sent[0].keyboard.inline_keyboard for button in row]
    done = next(
        button for button in buttons if ReactCb.unpack(button.callback_data).action == "done"
    )
    await feed.press(done.callback_data)

    assert await count_actions(session_factory, delivery.id) == 1
    still_expired = await fetch_one(session_factory, Occurrence, id=occurrence.id)
    assert still_expired.status is OccurrenceStatus.EXPIRED
    assert (await fetch_one(session_factory, Delivery, id=delivery.id)).status is (
        DeliveryStatus.SENT
    )


async def test_the_auto_expire_action_is_written_once_however_often_it_is_swept(
    session_factory, feed, fake_clock, fake_bot, settings, pills_category
):
    """Idempotency of the sweep, from the outside (tech.md 7.3)."""
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())
    await feed.message("/new")
    await feed.press(CatCb(category_id=pills_category, action="pick").pack())
    await feed.message("Выпить таблетку")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("09:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    await plan(session_factory, fake_clock, settings)
    user = await fetch_one(session_factory, User, tg_user_id=TG_USER_ID)
    reminder = await fetch_one(session_factory, Reminder, owner_id=user.id)
    occurrence = await fetch_one(session_factory, Occurrence, reminder_id=reminder.id)

    fake_clock.set(occurrence.fire_at)
    await dispatch(session_factory, fake_clock, fake_bot)
    delivery = await fetch_one(session_factory, Delivery, occurrence_id=occurrence.id)

    fake_clock.set(occurrence.expires_at + timedelta(minutes=1))
    first = await sweep(session_factory, fake_clock, fake_bot)
    second = await sweep(session_factory, fake_clock, fake_bot)

    assert (first.expired, second.expired) == (1, 0)
    assert await count_actions(session_factory, delivery.id, ActionKind.AUTO_EXPIRE) == 1
    assert len(fake_bot.edited) == 1
