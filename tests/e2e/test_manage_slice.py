"""S9 end to end: update -> handler -> service -> db, through real routers.

Acceptance criteria of tech.md 15 (S9): `/list` pages and filters by category,
the card opens from it, a pause stops the queue, editing changes one field at a
time, deleting asks first, and `/today` shows the day.
"""

from zoneinfo import ZoneInfo

import sqlalchemy as sa
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.methods import EditMessageText, GetMe

from app.bot.callbacks import (
    NO_CATEGORY_FILTER,
    CatCb,
    EditCb,
    ListCb,
    PageCb,
    RemCb,
    WizCb,
    pack_wall_time,
)
from app.db.models import Category, Occurrence, Reminder, User
from app.domain.contracts import REMINDER_NOTE_MAX_LENGTH, ReminderStatus
from app.domain.reminders import local_today
from app.services.planning import PlanningService
from tests.conftest import FROZEN_NOW
from tests.e2e.conftest import TG_USER_ID

TIMEZONE = "Europe/Moscow"
TODAY = local_today(FROZEN_NOW, ZoneInfo(TIMEZONE))


async def seed_categories(session_factory) -> tuple[int, int]:
    async with session_factory() as session:
        water = Category(owner_id=None, code="water", title="Вода", emoji="💧", is_system=True)
        pills = Category(owner_id=None, code="pills", title="Таблетки", emoji="💊", is_system=True)
        session.add_all([water, pills])
        await session.commit()
        return water.id, pills.id


async def fetch_user(session_factory) -> User:
    async with session_factory() as session:
        stmt = sa.select(User).where(User.tg_user_id == TG_USER_ID)
        return (await session.execute(stmt)).scalars().one()


async def fetch_reminders(session_factory) -> list[Reminder]:
    async with session_factory() as session:
        stmt = sa.select(Reminder).order_by(Reminder.id)
        return list((await session.execute(stmt)).scalars().all())


async def count_occurrences(session_factory) -> int:
    async with session_factory() as session:
        stmt = sa.select(sa.func.count()).select_from(Occurrence)
        return int((await session.execute(stmt)).scalar_one())


def last_text(telegram) -> str:
    return telegram.requests[-1].text


async def onboard(feed) -> None:
    await feed.message("/start")
    await feed.message(TIMEZONE)


async def create_daily(feed, category_id: int, title: str, at: str = "09:00") -> None:
    """The wizard of S3, used here only to get a reminder to manage."""
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message(title)
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time(at)).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())


async def plan(session_factory, context) -> None:
    async with session_factory() as session:
        await PlanningService(
            session,
            context.clock,
            horizon_hours=context.settings.planner_horizon_hours,
            occurrence_ttl_minutes=context.settings.occurrence_ttl_minutes,
        ).materialize()


async def test_the_list_shows_what_was_created(session_factory, feed, telegram):
    water, pills = await seed_categories(session_factory)
    await onboard(feed)
    await create_daily(feed, water, "Пить воду")
    await create_daily(feed, pills, "Таблетки")

    await feed.message("/list")

    text = last_text(telegram)
    assert "Пить воду" in text and "Таблетки" in text
    assert "Напоминания (2)" in text


async def test_the_filter_survives_the_screen_it_is_set_on(session_factory, feed, telegram):
    water, pills = await seed_categories(session_factory)
    await onboard(feed)
    await create_daily(feed, water, "Пить воду")
    await create_daily(feed, pills, "Таблетки")

    await feed.message("/list")
    await feed.press(WizCb(step="filter", value=str(NO_CATEGORY_FILTER)).pack())
    await feed.press(ListCb(category_id=pills, page=0).pack())

    text = last_text(telegram)
    assert "Таблетки" in text and "Пить воду" not in text
    assert "Фильтр" in text


async def test_the_card_opens_from_the_list(session_factory, feed, telegram):
    water, _ = await seed_categories(session_factory)
    await onboard(feed)
    await create_daily(feed, water, "Пить воду")
    reminder = (await fetch_reminders(session_factory))[0]

    await feed.message("/list")
    await feed.press(RemCb(reminder_id=reminder.id, action="open").pack())

    text = last_text(telegram)
    assert "Пить воду" in text
    assert "активно" in text
    assert "каждый день в 09:00" in text


class TestPause:
    async def test_a_pause_empties_the_queue_and_a_resume_refills_it(
        self, session_factory, feed, telegram, context
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]
        await plan(session_factory, context)
        assert await count_occurrences(session_factory) > 0

        await feed.press(RemCb(reminder_id=reminder.id, action="pause").pack())

        assert await count_occurrences(session_factory) == 0
        assert "на паузе" in last_text(telegram)

        await feed.press(RemCb(reminder_id=reminder.id, action="resume").pack())
        await plan(session_factory, context)

        assert await count_occurrences(session_factory) > 0
        assert "активно" in last_text(telegram)

    async def test_pressing_pause_twice_leaves_one_paused_reminder(
        self, session_factory, feed, telegram, context
    ):
        """Idempotency (tech.md 10): the second press changes nothing."""
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]
        await plan(session_factory, context)

        await feed.press(RemCb(reminder_id=reminder.id, action="pause").pack())
        await feed.press(RemCb(reminder_id=reminder.id, action="pause").pack())

        stored = (await fetch_reminders(session_factory))[0]
        assert stored.status is ReminderStatus.PAUSED
        assert stored.fired_count == 0
        assert await count_occurrences(session_factory) == 0

    async def test_a_paused_reminder_is_marked_in_the_list(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="pause").pack())
        await feed.message("/list")

        assert "⏸" in last_text(telegram)


class TestEdit:
    async def test_a_new_title_lands_on_the_card(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="title").pack())
        await feed.message("Пить больше воды")

        assert (await fetch_reminders(session_factory))[0].title == "Пить больше воды"
        assert "Пить больше воды" in last_text(telegram)

    async def test_a_note_is_written_and_then_taken_away(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="note").pack())
        await feed.message("стакан за раз")
        assert "стакан за раз" in last_text(telegram)

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="note").pack())
        await feed.press(WizCb(step="note", value="clear").pack())

        assert (await fetch_reminders(session_factory))[0].note is None

    async def test_a_note_longer_than_the_column_is_refused_by_name(
        self, session_factory, feed, telegram
    ):
        """The user hears what is wrong, not that something went wrong."""
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="note").pack())
        await feed.message("a" * (REMINDER_NOTE_MAX_LENGTH + 1))

        assert (await fetch_reminders(session_factory))[0].note is None
        assert "1000" in last_text(telegram)

    async def test_a_step_off_a_button_lands_on_the_card(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="snooze").pack())
        await feed.press(WizCb(step="snooze", value="15").pack())

        assert (await fetch_reminders(session_factory))[0].snooze_minutes == 15
        assert "отложить на 15 мин" in last_text(telegram)

    async def test_a_hand_typed_step_out_of_range_is_refused(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="snooze").pack())
        await feed.press(WizCb(step="snooze", value="man").pack())
        await feed.message("99999")

        assert (await fetch_reminders(session_factory))[0].snooze_minutes == 10
        assert "от 1 до 1440" in last_text(telegram)

        await feed.message("25")

        assert (await fetch_reminders(session_factory))[0].snooze_minutes == 25

    async def test_the_repeat_is_switched_on_and_off(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="repeat").pack())
        await feed.press(WizCb(step="repeat", value="30").pack())
        assert (await fetch_reminders(session_factory))[0].repeat_after_minutes == 30

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="repeat").pack())
        await feed.press(WizCb(step="repeat", value="off").pack())

        assert (await fetch_reminders(session_factory))[0].repeat_after_minutes is None

    async def test_the_category_moves_with_the_shared_picker(self, session_factory, feed, telegram):
        water, pills = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="category").pack())
        await feed.press(CatCb(category_id=pills, action="pick").pack())

        assert (await fetch_reminders(session_factory))[0].category_id == pills
        assert "💊" in last_text(telegram)

    async def test_a_new_schedule_goes_through_the_wizard_and_clears_the_queue(
        self, session_factory, feed, telegram, context
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]
        await plan(session_factory, context)
        before = await count_occurrences(session_factory)
        assert before > 0

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="schedule").pack())
        await feed.press(WizCb(step="kind", value="weekly").pack())
        await feed.press(WizCb(step="wday", value="3").pack())
        await feed.press(WizCb(step="wday", value="ok").pack())
        await feed.press(WizCb(step="time", value=pack_wall_time("07:00")).pack())
        await feed.press(WizCb(step="times", value="ok").pack())
        await feed.press(WizCb(step="confirm", value="yes").pack())

        stored = (await fetch_reminders(session_factory))[0]
        assert stored.schedule["kind"] == "weekly"
        assert stored.schedule["weekdays"] == [3]
        assert await count_occurrences(session_factory) == 0
        # The title was not asked again, so it must have survived the detour.
        assert stored.title == "Пить воду"

    async def test_cancelling_an_edit_leaves_the_reminder_alone(
        self, session_factory, feed, telegram
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="snooze").pack())
        await feed.press(WizCb(step="confirm", value="no").pack())

        assert (await fetch_reminders(session_factory))[0].snooze_minutes == 10
        assert "Пить воду" in last_text(telegram)

    async def test_typing_after_a_cancel_is_not_taken_as_an_answer(
        self, session_factory, feed, telegram
    ):
        """The state was cleared, so the next message is not a new title."""
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())
        await feed.press(EditCb(reminder_id=reminder.id, field="title").pack())
        await feed.press(WizCb(step="confirm", value="no").pack())
        await feed.message("не название")

        assert (await fetch_reminders(session_factory))[0].title == "Пить воду"


class TestDelete:
    async def test_deleting_asks_first(self, session_factory, feed, telegram):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="delete").pack())

        assert "Удалить" in last_text(telegram)
        assert len(await fetch_reminders(session_factory)) == 1

    async def test_cancelling_the_question_brings_the_card_back(
        self, session_factory, feed, telegram
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="delete").pack())
        await feed.press(RemCb(reminder_id=reminder.id, action="open").pack())

        assert len(await fetch_reminders(session_factory)) == 1
        assert "Статус" in last_text(telegram)

    async def test_confirming_removes_the_reminder_and_its_queue(
        self, session_factory, feed, telegram, context
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]
        await plan(session_factory, context)

        await feed.press(RemCb(reminder_id=reminder.id, action="delete").pack())
        await feed.press(RemCb(reminder_id=reminder.id, action="confirm_delete").pack())

        assert await fetch_reminders(session_factory) == []
        assert await count_occurrences(session_factory) == 0
        assert "Напоминаний пока нет" in last_text(telegram)

    async def test_confirming_twice_is_answered_once_and_not_found_after(
        self, session_factory, feed, telegram
    ):
        """Idempotency (tech.md 10): the row is gone, and the second press says so."""
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        await feed.press(RemCb(reminder_id=reminder.id, action="confirm_delete").pack())
        await feed.press(RemCb(reminder_id=reminder.id, action="confirm_delete").pack())

        assert await fetch_reminders(session_factory) == []
        assert telegram.answers[-1].text == "Не нашёл такую запись."


class TestToday:
    async def test_the_day_lists_what_is_planned_for_it(
        self, session_factory, feed, telegram, context, fake_clock
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду", at="21:00")
        await plan(session_factory, context)

        await feed.message("/today")

        text = last_text(telegram)
        assert "Пить воду" in text
        assert "21:00" in text

    async def test_an_empty_day_says_so(self, session_factory, feed, telegram):
        await seed_categories(session_factory)
        await onboard(feed)

        await feed.message("/today")

        assert last_text(telegram) == "На сегодня ничего нет."

    async def test_the_day_pages_without_a_filter(self, session_factory, feed, telegram, context):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду", at="21:00")
        await plan(session_factory, context)

        await feed.message("/today")
        await feed.press(PageCb(scope="today", page=0).pack())

        assert "Пить воду" in last_text(telegram)


class TestErrorPaths:
    """The slice draws its screens through Telegram, so it meets its errors."""

    async def test_a_redraw_that_changes_nothing_is_not_an_error(
        self, session_factory, feed, telegram
    ):
        """Telegram answers an identical edit with `message is not modified`."""
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]
        await feed.press(RemCb(reminder_id=reminder.id, action="open").pack())

        telegram.fail_next(
            TelegramBadRequest(method=GetMe(), message="Bad Request: message is not modified"),
            on=EditMessageText,
        )
        await feed.press(RemCb(reminder_id=reminder.id, action="open").pack())

        assert telegram.answers[-1].text is None

    async def test_a_rate_limited_redraw_keeps_the_pause(self, session_factory, feed, telegram):
        """The status was committed before the card; the row must survive it."""
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        telegram.fail_next(
            TelegramRetryAfter(method=GetMe(), message="Flood", retry_after=5),
            on=EditMessageText,
        )
        await feed.press(RemCb(reminder_id=reminder.id, action="pause").pack())

        assert (await fetch_reminders(session_factory))[0].status is ReminderStatus.PAUSED
        assert telegram.answers[-1].text == "Что-то пошло не так. Попробуй ещё раз."

    async def test_a_blocked_bot_does_not_delete_the_reminder_twice(
        self, session_factory, feed, telegram
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]

        telegram.fail_next(
            TelegramForbiddenError(method=GetMe(), message="blocked"), on=EditMessageText
        )
        await feed.press(RemCb(reminder_id=reminder.id, action="confirm_delete").pack())
        await feed.press(RemCb(reminder_id=reminder.id, action="confirm_delete").pack())

        assert await fetch_reminders(session_factory) == []

    async def test_a_stale_button_on_a_deleted_reminder_is_answered_not_found(
        self, session_factory, feed, telegram
    ):
        water, _ = await seed_categories(session_factory)
        await onboard(feed)
        await create_daily(feed, water, "Пить воду")
        reminder = (await fetch_reminders(session_factory))[0]
        await feed.press(RemCb(reminder_id=reminder.id, action="confirm_delete").pack())

        await feed.press(RemCb(reminder_id=reminder.id, action="edit").pack())

        assert telegram.answers[-1].text == "Не нашёл такую запись."
