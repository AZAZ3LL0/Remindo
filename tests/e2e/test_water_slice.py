"""Reference slice end to end: update -> handler -> service -> db -> planner ->
dispatcher -> FakeBotGateway -> reaction -> statistics."""

import pytest_asyncio
import sqlalchemy as sa

from app.bot.callbacks import CatCb, ReactCb, WizCb
from app.db.models import Category, Delivery, DeliveryAction, Occurrence, Reminder, User
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.services.dispatching import DispatchingService
from app.services.planning import PlanningService
from app.services.stats import StatsService
from tests.e2e.conftest import CHAT_ID, TG_USER_ID


@pytest_asyncio.fixture
async def water_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(owner_id=None, code="water", title="Вода", emoji="💧", is_system=True)
        session.add(category)
        await session.commit()
        return category.id


async def fetch_one(session_factory, model, **filters):
    async with session_factory() as session:
        stmt = sa.select(model)
        for column, value in filters.items():
            stmt = stmt.where(getattr(model, column) == value)
        return (await session.execute(stmt)).scalars().first()


async def test_water_slice_from_start_to_statistics(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, water_category
):
    # 1. The user says hello and gets asked for a timezone.
    await feed.message("/start")
    user = await fetch_one(session_factory, User, tg_user_id=TG_USER_ID)
    assert user is not None
    assert "таймзоне" in telegram.sent_messages[-1].text

    await feed.press(WizCb(step="tz", value="Europe/Moscow").pack())
    user = await fetch_one(session_factory, User, tg_user_id=TG_USER_ID)
    assert user.timezone == "Europe/Moscow"
    assert user.onboarded_at is not None

    # 2. The wizard creates an interval reminder.
    await feed.message("/new")
    await feed.press(CatCb(category_id=water_category, action="pick").pack())
    await feed.message("Пить воду")
    await feed.press(WizCb(step="every", value="120").pack())
    await feed.press(WizCb(step="window", value="09002100").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    reminder = await fetch_one(session_factory, Reminder, owner_id=user.id)
    assert reminder is not None
    assert reminder.schedule == {
        "kind": "interval",
        "every_minutes": 120,
        "window_start": "09:00",
        "window_end": "21:00",
    }

    # 3. The planner materialises the queue.
    async with session_factory() as session:
        planned = await PlanningService(
            session,
            fake_clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()
    assert planned.occurrences_created > 0
    assert planned.deliveries_created == planned.occurrences_created

    # 4. Time reaches the first planned moment and the dispatcher delivers it.
    async with session_factory() as session:
        first_fire_at = (
            await session.execute(sa.select(sa.func.min(Occurrence.fire_at)))
        ).scalar_one()
    fake_clock.set(first_fire_at)
    async with session_factory() as session:
        dispatched = await DispatchingService(
            session, fake_clock, fake_bot, batch_size=10, lock_seconds=60
        ).deliver()
    assert dispatched.sent == 1

    message = fake_bot.sent[0]
    assert message.chat_id == CHAT_ID
    assert "Пить воду" in message.text
    buttons = [button for row in message.keyboard.inline_keyboard for button in row]
    reaction = ReactCb.unpack(buttons[0].callback_data)
    assert reaction.action == "done"

    # 5. The user presses Done; the message loses its buttons.
    await feed.press(buttons[0].callback_data)

    delivery = await fetch_one(session_factory, Delivery, id=reaction.delivery_id)
    assert delivery.status is DeliveryStatus.DONE
    assert delivery.reacted_at is not None
    occurrence = await fetch_one(session_factory, Occurrence, id=delivery.occurrence_id)
    assert occurrence.status is OccurrenceStatus.DONE
    assert telegram.edits, "the reminder message must be edited after a reaction"

    action = await fetch_one(session_factory, DeliveryAction, delivery_id=delivery.id)
    assert action.kind is ActionKind.DONE

    # 6. Pressing the same button again changes nothing.
    await feed.press(buttons[0].callback_data)
    async with session_factory() as session:
        actions = int(
            (
                await session.execute(
                    sa.select(sa.func.count()).where(DeliveryAction.delivery_id == delivery.id)
                )
            ).scalar_one()
        )
    assert actions == 1

    # 7. Statistics count the completion.
    async with session_factory() as session:
        summary = await StatsService(session, fake_clock).summary(user.id)
    assert summary.last_7_days.completed == 1
    assert summary.current_streak == 1
