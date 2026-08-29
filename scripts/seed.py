"""Shared fixtures for the team and the fakes. Running it twice changes nothing."""

import asyncio
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.models import Category, Reminder, ReminderRecipient, User
from app.db.session import create_engine, create_session_factory
from app.domain.contracts import RecipientRole, ReminderStatus
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    OnceSchedule,
    Schedule,
    dump_schedule,
)

_log = get_logger(__name__)

SYSTEM_CATEGORIES = (
    ("pills", "Таблетки", "💊", 10),
    ("water", "Вода", "💧", 20),
    ("workout", "Зарядка", "🏃", 30),
    ("cooking", "Готовка", "🍳", 40),
    ("task", "Задача", "📌", 50),
    ("event", "Событие", "📅", 60),
)

DEMO_TG_USER_ID = 100_000_001
DEMO_TIMEZONE = "Europe/Moscow"


async def seed_system_categories(session: AsyncSession) -> int:
    rows = [
        {
            "owner_id": None,
            "code": code,
            "title": title,
            "emoji": emoji,
            "is_system": True,
            "sort_order": sort_order,
        }
        for code, title, emoji, sort_order in SYSTEM_CATEGORIES
    ]
    stmt = (
        pg_insert(Category)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["code"], index_where=sa.text("owner_id IS NULL"))
        .returning(Category.id)
    )
    return len((await session.execute(stmt)).scalars().all())


async def seed_demo_user(session: AsyncSession) -> User:
    stmt = sa.select(User).where(User.tg_user_id == DEMO_TG_USER_ID)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        tg_user_id=DEMO_TG_USER_ID,
        tg_chat_id=DEMO_TG_USER_ID,
        first_name="Demo",
        username="demo",
        language="ru",
        timezone=DEMO_TIMEZONE,
        onboarded_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def seed_demo_reminders(session: AsyncSession, user: User) -> int:
    now = SystemClock().now()
    demos: tuple[tuple[str, str, Schedule], ...] = (
        (
            "water",
            "Пить воду",
            IntervalSchedule(every_minutes=120, window_start="09:00", window_end="21:00"),
        ),
        ("pills", "Витамин D", DailySchedule(times=["08:00", "20:00"], every_n_days=1)),
        (
            "event",
            "Позвонить врачу",
            OnceSchedule(at=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")),
        ),
    )

    created = 0
    for code, title, schedule in demos:
        category = (
            await session.execute(
                sa.select(Category).where(Category.code == code, Category.owner_id.is_(None))
            )
        ).scalar_one()
        exists = (
            await session.execute(
                sa.select(Reminder.id).where(Reminder.owner_id == user.id, Reminder.title == title)
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue

        reminder = Reminder(
            owner_id=user.id,
            category_id=category.id,
            title=title,
            status=ReminderStatus.ACTIVE,
            schedule_kind=schedule.kind,
            schedule=dump_schedule(schedule),
            timezone=DEMO_TIMEZONE,
            starts_at=now,
        )
        session.add(reminder)
        await session.flush()
        session.add(
            ReminderRecipient(
                reminder_id=reminder.id,
                user_id=user.id,
                role=RecipientRole.OWNER,
                accepted_at=now,
            )
        )
        created += 1
    return created


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        categories = await seed_system_categories(session)
        user = await seed_demo_user(session)
        reminders = await seed_demo_reminders(session, user)
        await session.commit()

    await engine.dispose()
    _log.info(
        "seed.done", categories_created=categories, reminders_created=reminders, user_id=user.id
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
