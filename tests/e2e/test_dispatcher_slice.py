"""S5 end to end: wizard -> planner -> dispatcher -> FakeBotGateway -> reaction.

Acceptance criteria of tech.md 15 (S5): a due delivery leaves the queue exactly
once, a rate limit postpones it instead of losing it, and a blocked bot stops
the queue for that recipient without touching anyone else.
"""

from datetime import timedelta

import pytest_asyncio
import sqlalchemy as sa
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.bot.callbacks import CatCb, ReactCb, WizCb, pack_wall_time
from app.db.models import Category, Delivery, DeliveryAction, Occurrence, User
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.services.dispatching import DispatchingService
from app.services.planning import PlanningService
from tests.e2e.conftest import CHAT_ID, TG_USER_ID

TIMEZONE = "Europe/Moscow"
DAILY_TIME = "08:00"


@pytest_asyncio.fixture
async def pills_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(
            owner_id=None, code="pills", title="Таблетки", emoji="💊", is_system=True
        )
        session.add(category)
        await session.commit()
        return category.id


async def create_daily_reminder(feed, category_id: int) -> None:
    await feed.message("/start")
    await feed.message(TIMEZONE)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message("Выпить таблетки")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time(DAILY_TIME)).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())


async def plan_and_reach_the_first_moment(session_factory, fake_clock, settings) -> None:
    """Materialise the queue, then move the clock onto its first firing."""
    async with session_factory() as session:
        planned = await PlanningService(
            session,
            fake_clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()
    assert planned.deliveries_created > 0

    async with session_factory() as session:
        first_fire_at = (
            await session.execute(sa.select(sa.func.min(Occurrence.fire_at)))
        ).scalar_one()
    fake_clock.set(first_fire_at)


def dispatch(session_factory, fake_clock, fake_bot):
    async def _run():
        async with session_factory() as session:
            return await DispatchingService(
                session, fake_clock, fake_bot, batch_size=10, lock_seconds=60
            ).deliver()

    return _run()


async def fetch_delivery(session_factory) -> Delivery:
    """The delivery of the earliest occurrence: the only one due in these tests."""
    async with session_factory() as session:
        stmt = sa.select(Delivery).order_by(Delivery.id).limit(1)
        return (await session.execute(stmt)).scalars().one()


async def test_a_rate_limited_reminder_still_reaches_the_user(
    session_factory, feed, fake_clock, fake_bot, settings, pills_category
):
    """Flood control delays the message; it never drops it."""
    await create_daily_reminder(feed, pills_category)
    await plan_and_reach_the_first_moment(session_factory, fake_clock, settings)

    fake_bot.fail_next(TelegramRetryAfter(method=None, message="flood", retry_after=5))
    first = await dispatch(session_factory, fake_clock, fake_bot)

    assert (first.retried, fake_bot.sent) == (1, [])
    postponed = await fetch_delivery(session_factory)
    assert postponed.status is DeliveryStatus.PENDING
    # The retry budget is untouched, so a real failure still gets five tries.
    assert postponed.attempts == 0

    fake_clock.advance(timedelta(seconds=6))
    second = await dispatch(session_factory, fake_clock, fake_bot)

    assert second.sent == 1
    assert len(fake_bot.sent) == 1
    assert "Выпить таблетки" in fake_bot.sent[0].text
    assert fake_bot.sent[0].chat_id == CHAT_ID

    # The reaction on the delayed message works like any other.
    buttons = [button for row in fake_bot.sent[0].keyboard.inline_keyboard for button in row]
    done = next(
        button for button in buttons if ReactCb.unpack(button.callback_data).action == "done"
    )
    await feed.press(done.callback_data)

    delivered = await fetch_delivery(session_factory)
    assert delivered.status is DeliveryStatus.DONE
    async with session_factory() as session:
        kinds = (await session.execute(sa.select(DeliveryAction.kind))).scalars().all()
    assert list(kinds) == [ActionKind.DONE]


async def test_a_blocked_bot_stops_the_queue_for_that_user(
    session_factory, feed, fake_clock, fake_bot, settings, pills_category
):
    await create_daily_reminder(feed, pills_category)
    await plan_and_reach_the_first_moment(session_factory, fake_clock, settings)

    fake_bot.fail_next(TelegramForbiddenError(method=None, message="bot was blocked by the user"))
    blocked_cycle = await dispatch(session_factory, fake_clock, fake_bot)

    assert blocked_cycle.blocked == 1
    async with session_factory() as session:
        user = (
            (await session.execute(sa.select(User).where(User.tg_user_id == TG_USER_ID)))
            .scalars()
            .one()
        )
    assert user.is_blocked is True

    # Later occurrences of the same reminder are not attempted either.
    fake_clock.advance(timedelta(days=1))
    async with session_factory() as session:
        await PlanningService(
            session,
            fake_clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()
    later = await dispatch(session_factory, fake_clock, fake_bot)

    assert fake_bot.sent == []
    assert later.claimed > 0
    assert later.blocked == later.claimed


async def test_the_dispatcher_cycle_is_idempotent(
    session_factory, feed, fake_clock, fake_bot, settings, pills_category
):
    """Two cycles over the same queue send one message and write one occurrence."""
    await create_daily_reminder(feed, pills_category)
    await plan_and_reach_the_first_moment(session_factory, fake_clock, settings)

    await dispatch(session_factory, fake_clock, fake_bot)
    repeated = await dispatch(session_factory, fake_clock, fake_bot)

    assert repeated.claimed == 0
    assert len(fake_bot.sent) == 1
    delivered = await fetch_delivery(session_factory)
    assert delivered.status is DeliveryStatus.SENT
    async with session_factory() as session:
        occurrence = await session.get(Occurrence, delivered.occurrence_id)
    assert occurrence.status is OccurrenceStatus.SENT


async def test_an_expired_occurrence_is_never_delivered(
    session_factory, feed, fake_clock, fake_bot, settings, pills_category
):
    """A reminder nobody can answer any more must not be sent (tech.md 7.3)."""
    await create_daily_reminder(feed, pills_category)
    await plan_and_reach_the_first_moment(session_factory, fake_clock, settings)

    async with session_factory() as session:
        await session.execute(
            sa.update(Occurrence).values(status=OccurrenceStatus.EXPIRED),
        )
        await session.commit()

    result = await dispatch(session_factory, fake_clock, fake_bot)

    assert fake_bot.sent == []
    assert result.failed == result.claimed > 0
    assert (await fetch_delivery(session_factory)).error_code == "occurrence_closed"
