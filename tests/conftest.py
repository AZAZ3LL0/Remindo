"""Shared fixtures. Tests move FakeClock instead of sleeping."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import Category, Reminder, ReminderRecipient, User
from app.db.session import create_engine
from app.domain.contracts import RecipientRole, ReminderStatus, ScheduleKind
from app.domain.schedules import IntervalSchedule, Schedule, dump_schedule
from app.gateways.fakes import FakeBotGateway, FakeClock

#: Fixed point in time all deterministic tests start from.
FROZEN_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

DEFAULT_TEST_URL = "postgresql+asyncpg://app:app@db:5432/reminder_test"


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)


async def _ensure_database(url: str) -> None:
    """Create the throwaway test database if it is missing."""
    name = url.rsplit("/", 1)[1]
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url)
    try:
        async with engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            exists = await connection.scalar(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if not exists:
                await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database(database_url: str) -> str:
    """Schema is built once per session, exactly like production does it."""
    asyncio.run(_ensure_database(database_url))
    config = Config("alembic.ini")
    config.attributes["db_url"] = database_url
    command.upgrade(config, "head")
    return database_url


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    created = create_engine(migrated_database)
    yield created
    await created.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """One test, one transaction. Service commits become savepoint releases."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(FROZEN_NOW)


@pytest.fixture
def fake_bot() -> FakeBotGateway:
    return FakeBotGateway()


@pytest.fixture
def freeze_at(fake_clock: FakeClock) -> Callable[[datetime], datetime]:
    def _freeze(moment: datetime) -> datetime:
        return fake_clock.set(moment)

    return _freeze


@pytest_asyncio.fixture
async def user_factory(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    counter = iter(range(900_000_000, 900_100_000))

    async def _create(**overrides: object) -> User:
        tg_id = next(counter)
        user = User(
            **{
                "tg_user_id": tg_id,
                "tg_chat_id": tg_id,
                "first_name": "Test",
                "language": "ru",
                "timezone": "Europe/Moscow",
                **overrides,
            }
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _create


@pytest_asyncio.fixture
async def category_factory(db_session: AsyncSession) -> Callable[..., Awaitable[Category]]:
    counter = iter(range(1, 10_000))

    async def _create(**overrides: object) -> Category:
        index = next(counter)
        category = Category(
            **{
                "owner_id": None,
                "code": f"water_{index}",
                "title": "Вода",
                "emoji": "💧",
                "is_system": True,
                **overrides,
            }
        )
        db_session.add(category)
        await db_session.flush()
        return category

    return _create


@pytest_asyncio.fixture
async def reminder_factory(
    db_session: AsyncSession,
    user_factory: Callable[..., Awaitable[User]],
    category_factory: Callable[..., Awaitable[Category]],
) -> Callable[..., Awaitable[Reminder]]:
    async def _create(
        owner: User | None = None,
        category: Category | None = None,
        schedule: Schedule | None = None,
        starts_at: datetime | None = None,
        **overrides: object,
    ) -> Reminder:
        owner = owner or await user_factory()
        category = category or await category_factory()
        schedule = schedule or IntervalSchedule(
            every_minutes=120, window_start="09:00", window_end="21:00"
        )
        reminder = Reminder(
            **{
                "owner_id": owner.id,
                "category_id": category.id,
                "title": "Пить воду",
                "status": ReminderStatus.ACTIVE,
                "schedule_kind": ScheduleKind(schedule.kind),
                "schedule": dump_schedule(schedule),
                "timezone": owner.timezone,
                "starts_at": starts_at or FROZEN_NOW - timedelta(minutes=1),
                **overrides,
            }
        )
        db_session.add(reminder)
        await db_session.flush()
        db_session.add(
            ReminderRecipient(
                reminder_id=reminder.id,
                user_id=owner.id,
                role=RecipientRole.OWNER,
                accepted_at=FROZEN_NOW,
            )
        )
        await db_session.flush()
        return reminder

    return _create
