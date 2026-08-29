"""S2 end to end: update -> handler -> service -> db, through real routers.

Acceptance criteria of tech.md 15 (S2): the list shows system presets next to
the user's own, a category is created with an emoji, renamed and archived, a
category with live reminders refuses to be archived, and pressing the same
button twice changes nothing.
"""

import sqlalchemy as sa
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.methods import EditMessageText, GetMe

from app.bot.callbacks import CatCb, PageCb, WizCb
from app.db.models import Category, Reminder, ReminderRecipient, User
from app.domain.contracts import RecipientRole, ReminderStatus, ScheduleKind
from app.domain.schedules import DailySchedule, dump_schedule
from tests.conftest import FROZEN_NOW
from tests.e2e.conftest import TG_USER_ID

SYSTEM_PRESETS = (("water", "Вода", "💧"), ("pills", "Таблетки", "💊"))


async def seed_presets(session_factory) -> None:
    async with session_factory() as session:
        for order, (code, title, emoji) in enumerate(SYSTEM_PRESETS, start=1):
            session.add(
                Category(
                    owner_id=None,
                    code=code,
                    title=title,
                    emoji=emoji,
                    is_system=True,
                    sort_order=order,
                )
            )
        await session.commit()


async def fetch_user(session_factory) -> User:
    async with session_factory() as session:
        stmt = sa.select(User).where(User.tg_user_id == TG_USER_ID)
        return (await session.execute(stmt)).scalars().one()


async def own_categories(session_factory) -> list[Category]:
    user = await fetch_user(session_factory)
    async with session_factory() as session:
        stmt = sa.select(Category).where(Category.owner_id == user.id).order_by(Category.id)
        return list((await session.execute(stmt)).scalars().all())


async def add_reminder(session_factory, category_id: int, status: ReminderStatus) -> None:
    """A live reminder in the category, the way the wizard would leave one."""
    user = await fetch_user(session_factory)
    schedule = DailySchedule(times=["08:00"])
    async with session_factory() as session:
        reminder = Reminder(
            owner_id=user.id,
            category_id=category_id,
            title="Пить воду",
            status=status,
            schedule_kind=ScheduleKind(schedule.kind),
            schedule=dump_schedule(schedule),
            timezone=user.timezone,
            starts_at=FROZEN_NOW,
        )
        session.add(reminder)
        await session.flush()
        session.add(
            ReminderRecipient(
                reminder_id=reminder.id,
                user_id=user.id,
                role=RecipientRole.OWNER,
                accepted_at=FROZEN_NOW,
            )
        )
        await session.commit()


def last_text(telegram) -> str:
    return telegram.requests[-1].text


def texts(telegram) -> str:
    return "\n".join(
        request.text for request in telegram.requests if getattr(request, "text", None)
    )


async def onboard(feed) -> None:
    await feed.message("/start")
    await feed.message("Europe/Moscow")


async def create_category(feed, title: str, emoji: str = "📚") -> None:
    await feed.message("/categories")
    await feed.press(WizCb(step="cat", value="new").pack())
    await feed.message(title)
    await feed.press(WizCb(step="emoji", value=emoji).pack())


async def test_the_list_shows_system_presets(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)

    await feed.message("/categories")

    assert "Вода" in last_text(telegram)
    assert "Таблетки" in last_text(telegram)


async def test_a_category_is_created_with_a_title_and_an_emoji(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)

    await create_category(feed, "Учёба", "📚")

    categories = await own_categories(session_factory)
    assert [(item.title, item.emoji, item.is_system) for item in categories] == [
        ("Учёба", "📚", False)
    ]
    assert "Учёба" in last_text(telegram)


async def test_a_typed_emoji_is_accepted_and_junk_is_not(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)

    await feed.message("/categories")
    await feed.press(WizCb(step="cat", value="new").pack())
    await feed.message("Хобби")
    await feed.message("две штуки 💊💧")

    assert "Нужно ровно одно эмодзи" in last_text(telegram)
    assert await own_categories(session_factory) == []

    # The form survived the mistake, so the next attempt still counts.
    await feed.message("🎸")

    assert [item.emoji for item in await own_categories(session_factory)] == ["🎸"]


async def test_an_empty_title_keeps_the_question_open(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)

    await feed.message("/categories")
    await feed.press(WizCb(step="cat", value="new").pack())
    await feed.message("   ")

    assert "Название" in last_text(telegram)
    assert await own_categories(session_factory) == []


async def test_a_second_category_under_the_same_title_is_refused(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    await create_category(feed, "Спорт", "🏃")

    await create_category(feed, "  спорт", "🧘")

    assert len(await own_categories(session_factory)) == 1
    assert "уже есть" in texts(telegram)


async def test_a_category_is_renamed_and_keeps_its_code(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    await create_category(feed, "Спорт", "🏃")
    created = (await own_categories(session_factory))[0]

    await feed.press(CatCb(category_id=created.id, action="rename").pack())
    await feed.message("Зарядка")

    renamed = (await own_categories(session_factory))[0]
    assert (renamed.title, renamed.code) == ("Зарядка", created.code)
    assert "Зарядка" in last_text(telegram)


async def test_a_category_is_archived_and_leaves_the_list(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    await create_category(feed, "Спорт", "🏃")
    created = (await own_categories(session_factory))[0]

    await feed.press(CatCb(category_id=created.id, action="archive").pack())
    assert "архив" in last_text(telegram)

    await feed.press(CatCb(category_id=created.id, action="confirm_archive").pack())

    assert (await own_categories(session_factory))[0].archived_at >= FROZEN_NOW
    assert "Спорт" not in last_text(telegram)


async def test_archiving_a_category_with_a_live_reminder_is_refused(
    session_factory, feed, telegram
):
    await seed_presets(session_factory)
    await onboard(feed)
    await create_category(feed, "Спорт", "🏃")
    created = (await own_categories(session_factory))[0]
    await add_reminder(session_factory, created.id, ReminderStatus.ACTIVE)

    await feed.press(CatCb(category_id=created.id, action="confirm_archive").pack())

    assert (await own_categories(session_factory))[0].archived_at is None
    assert "напоминания" in telegram.answers[-1].text


async def test_archiving_twice_archives_once(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    await create_category(feed, "Спорт", "🏃")
    created = (await own_categories(session_factory))[0]

    await feed.press(CatCb(category_id=created.id, action="confirm_archive").pack())
    archived_at = (await own_categories(session_factory))[0].archived_at
    await feed.press(CatCb(category_id=created.id, action="confirm_archive").pack())

    assert (await own_categories(session_factory))[0].archived_at == archived_at
    assert "уже в архиве" in telegram.answers[-1].text


async def test_creation_pressed_twice_creates_one_category(session_factory, feed, telegram):
    """The second press replays a stale button; the form is already finished."""
    await seed_presets(session_factory)
    await onboard(feed)

    await feed.message("/categories")
    await feed.press(WizCb(step="cat", value="new").pack())
    await feed.message("Спорт")
    await feed.press(WizCb(step="emoji", value="🏃").pack())
    await feed.press(WizCb(step="emoji", value="🏃").pack())

    assert len(await own_categories(session_factory)) == 1


async def test_a_system_category_offers_no_editing(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    async with session_factory() as session:
        stmt = sa.select(Category).where(Category.code == "water")
        water = (await session.execute(stmt)).scalars().one()

    await feed.message("/categories")
    await feed.press(CatCb(category_id=water.id, action="open").pack())

    assert "системная" in last_text(telegram)

    await feed.press(CatCb(category_id=water.id, action="rename").pack())

    assert "Системную категорию менять нельзя" in telegram.answers[-1].text


async def test_a_foreign_category_is_not_reachable(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    async with session_factory() as session:
        stranger = User(tg_user_id=1, tg_chat_id=1, first_name="Чужой")
        session.add(stranger)
        await session.flush()
        session.add(Category(owner_id=stranger.id, code="secret", title="Секрет", emoji="🔒"))
        await session.commit()
        secret_id = (
            await session.execute(sa.select(Category.id).where(Category.code == "secret"))
        ).scalar_one()

    await feed.press(CatCb(category_id=secret_id, action="open").pack())

    assert telegram.answers[-1].text == "Не нашёл такую запись."


async def test_cancelling_the_form_leaves_no_category_and_reopens_the_list(
    session_factory, feed, telegram
):
    await seed_presets(session_factory)
    await onboard(feed)

    await feed.message("/categories")
    await feed.press(WizCb(step="cat", value="new").pack())
    await feed.message("Спорт")
    await feed.press(WizCb(step="cat", value="cancel").pack())

    assert await own_categories(session_factory) == []
    assert "Категории" in last_text(telegram)


async def test_the_list_paginates_without_losing_the_new_button(session_factory, feed, telegram):
    await seed_presets(session_factory)
    await onboard(feed)
    for index in range(8):
        await create_category(feed, f"Хобби {index}", "🎸")

    await feed.message("/categories")
    await feed.press(PageCb(scope="cat", page=1).pack())

    assert "Хобби 7" in last_text(telegram)
    assert WizCb(step="cat", value="new").pack() in _callbacks(telegram.requests[-1])


def _callbacks(request) -> set[str]:
    markup = request.reply_markup
    if markup is None:
        return set()
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


class TestTelegramRefuses:
    """The transport fails; the row and the form must not (tech.md 10)."""

    async def test_a_redraw_that_changes_nothing_is_not_an_error(
        self, session_factory, feed, telegram
    ):
        """Telegram answers an identical edit with `message is not modified`."""
        await seed_presets(session_factory)
        await onboard(feed)
        await feed.message("/categories")

        telegram.fail_next(
            TelegramBadRequest(method=GetMe(), message="Bad Request: message is not modified"),
            on=EditMessageText,
        )
        await feed.press(PageCb(scope="cat", page=0).pack())

        assert not [answer for answer in telegram.answers if answer.text]

    async def test_a_rate_limit_keeps_the_created_category(self, session_factory, feed, telegram):
        """The commit happened before the redraw, so the row must survive it."""
        await seed_presets(session_factory)
        await onboard(feed)
        await feed.message("/categories")
        await feed.press(WizCb(step="cat", value="new").pack())
        await feed.message("Спорт")

        telegram.fail_next(
            TelegramRetryAfter(method=GetMe(), message="Flood", retry_after=5),
            on=EditMessageText,
        )
        await feed.press(WizCb(step="emoji", value="🏃").pack())

        assert [item.title for item in await own_categories(session_factory)] == ["Спорт"]
        assert telegram.answers[-1].text == "Что-то пошло не так. Попробуй ещё раз."

    async def test_a_blocked_bot_does_not_archive_anything_twice(
        self, session_factory, feed, telegram
    ):
        """A failed redraw must not turn into a second archiving attempt."""
        await seed_presets(session_factory)
        await onboard(feed)
        await create_category(feed, "Спорт", "🏃")
        created = (await own_categories(session_factory))[0]

        telegram.fail_next(
            TelegramForbiddenError(method=GetMe(), message="blocked"), on=EditMessageText
        )
        await feed.press(CatCb(category_id=created.id, action="confirm_archive").pack())
        archived_at = (await own_categories(session_factory))[0].archived_at

        await feed.press(CatCb(category_id=created.id, action="confirm_archive").pack())

        assert (await own_categories(session_factory))[0].archived_at == archived_at
