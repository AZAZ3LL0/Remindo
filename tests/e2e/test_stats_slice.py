"""S11 end to end: a reaction becomes a number, a screen and a weekly message.

Acceptance criteria of tech.md 15 (S11): a streak per category, the share done
over seven and thirty days, `/stats`, and the weekly digest. Everything here
goes through real routers and the real worker cycle; only Telegram is fake.
"""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
import sqlalchemy as sa

from app.bot.callbacks import (
    NO_CATEGORY_FILTER,
    CatCb,
    ReactCb,
    SetCb,
    StatCb,
    WizCb,
    pack_wall_time,
)
from app.bot.render.texts import T
from app.db.models import Category, Occurrence, User
from app.services.digest import DigestService
from app.services.dispatching import DispatchingService
from app.services.planning import PlanningService

TIMEZONE = "Europe/Moscow"
LANG = "ru"
DAILY_TIME = "08:00"

#: Monday 09:00 Moscow: the moment the digest cycle keys a week on.
MONDAY_NINE = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def categories(session_factory) -> dict[str, int]:
    async with session_factory() as session:
        water = Category(owner_id=None, code="water", title="Вода", emoji="💧", is_system=True)
        pills = Category(owner_id=None, code="pills", title="Таблетки", emoji="💊", is_system=True)
        session.add_all([water, pills])
        await session.commit()
        return {"water": water.id, "pills": pills.id}


async def onboard(feed) -> None:
    await feed.message("/start")
    await feed.message(TIMEZONE)


async def create_daily_reminder(feed, category_id: int, title: str) -> None:
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message(title)
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time(DAILY_TIME)).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())


async def deliver_next(session_factory, fake_clock, fake_bot, settings):
    """Materialise, jump to the first unsent moment and deliver it."""
    async with session_factory() as session:
        await PlanningService(
            session,
            fake_clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()

    async with session_factory() as session:
        stmt = sa.select(sa.func.min(Occurrence.fire_at)).where(
            Occurrence.fire_at > fake_clock.now()
        )
        moment = (await session.execute(stmt)).scalar_one_or_none()
    if moment is None:
        return []

    fake_clock.set(moment)
    before = len(fake_bot.sent)
    async with session_factory() as session:
        await DispatchingService(
            session, fake_clock, fake_bot, batch_size=10, lock_seconds=60
        ).deliver()
    return fake_bot.sent[before:]


def buttons_of(message) -> dict[str, str]:
    return {
        ReactCb.unpack(button.callback_data).action: button.callback_data
        for row in message.keyboard.inline_keyboard
        for button in row
    }


async def answer_next(session_factory, feed, fake_clock, fake_bot, settings, action: str) -> None:
    sent = await deliver_next(session_factory, fake_clock, fake_bot, settings)
    assert sent, "the planner produced nothing to answer"
    await feed.press(buttons_of(sent[-1])[action])


async def run_digest(session_factory, fake_clock, fake_bot):
    async with session_factory() as session:
        return await DigestService(
            session, fake_clock, fake_bot, weekday=1, hour=9, batch_size=10
        ).run()


async def fetch_user(session_factory) -> User:
    async with session_factory() as session:
        return (await session.execute(sa.select(User).limit(1))).scalars().one()


async def test_answered_reminders_become_a_streak_and_a_breakdown(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, categories
):
    fake_clock.set(datetime(2026, 5, 28, 5, 0, tzinfo=UTC))  # Thursday, 08:00 Moscow
    await onboard(feed)
    await create_daily_reminder(feed, categories["water"], "Пить воду")
    await create_daily_reminder(feed, categories["pills"], "Витамины")

    # Two mornings answered: one done in each category, then one skipped.
    await answer_next(session_factory, feed, fake_clock, fake_bot, settings, "done")
    await answer_next(session_factory, feed, fake_clock, fake_bot, settings, "done")
    await answer_next(session_factory, feed, fake_clock, fake_bot, settings, "skip")

    await feed.message("/stats")
    screen = telegram.sent_messages[-1]

    assert T("stats.title", LANG) in screen.text
    assert "Вода" in screen.text and "Таблетки" in screen.text
    # Two done out of three outcomes, both windows counting the same three.
    assert "67%" in screen.text

    rows = {
        StatCb.unpack(button.callback_data).category_id
        for row in screen.reply_markup.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("t:")
    }
    assert {categories["water"], categories["pills"]} <= rows


async def test_a_category_row_opens_that_slice_and_leads_back(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, categories
):
    fake_clock.set(datetime(2026, 5, 28, 5, 0, tzinfo=UTC))
    await onboard(feed)
    await create_daily_reminder(feed, categories["water"], "Пить воду")
    await answer_next(session_factory, feed, fake_clock, fake_bot, settings, "done")

    await feed.message("/stats")
    await feed.press(StatCb(category_id=categories["water"], page=0).pack())

    card = telegram.edits[-1]
    assert "Вода" in card.text
    assert "Таблетки" not in card.text

    back = [
        button.callback_data
        for row in card.reply_markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert back == [StatCb(category_id=NO_CATEGORY_FILTER, page=0).pack()]

    await feed.press(back[0])
    assert T("stats.title", LANG) in telegram.edits[-1].text


async def test_the_weekly_digest_reaches_the_chat_once(
    session_factory, feed, fake_clock, fake_bot, settings, categories
):
    fake_clock.set(datetime(2026, 5, 28, 5, 0, tzinfo=UTC))
    await onboard(feed)
    await create_daily_reminder(feed, categories["water"], "Пить воду")
    await answer_next(session_factory, feed, fake_clock, fake_bot, settings, "done")

    fake_clock.set(MONDAY_NINE + timedelta(hours=1))
    before = len(fake_bot.sent)

    assert (await run_digest(session_factory, fake_clock, fake_bot)).sent == 1
    digest = fake_bot.sent[-1]
    assert digest.keyboard is None
    assert "Вода" in digest.text

    # The same cycle a minute later owes nothing: the week is already marked.
    fake_clock.set(MONDAY_NINE + timedelta(hours=1, minutes=1))
    assert (await run_digest(session_factory, fake_clock, fake_bot)).sent == 0
    assert len(fake_bot.sent) == before + 1

    user = await fetch_user(session_factory)
    assert user.digest_sent_at == MONDAY_NINE


async def test_turning_the_digest_off_stops_it(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, categories
):
    fake_clock.set(datetime(2026, 5, 28, 5, 0, tzinfo=UTC))
    await onboard(feed)
    await create_daily_reminder(feed, categories["water"], "Пить воду")
    await answer_next(session_factory, feed, fake_clock, fake_bot, settings, "done")

    await feed.message("/settings")
    assert T("settings.digest_on", LANG) in telegram.sent_messages[-1].text

    await feed.press(SetCb(field="digest", value="off").pack())
    assert T("settings.digest_off", LANG) in telegram.edits[-1].text
    assert (await fetch_user(session_factory)).digest_enabled is False

    fake_clock.set(MONDAY_NINE + timedelta(hours=1))
    before = len(fake_bot.sent)

    assert (await run_digest(session_factory, fake_clock, fake_bot)).considered == 0
    assert len(fake_bot.sent) == before
    # Nothing was marked either, so turning it back on does not replay the week.
    assert (await fetch_user(session_factory)).digest_sent_at is None
