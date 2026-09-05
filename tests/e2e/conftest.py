"""Fixtures that assemble the bot process for end-to-end runs."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.main import HANDLER_MODULES, build_dispatcher
from app.core.config import Settings
from app.core.di import AppContext
from app.db.session import create_session_factory
from tests.e2e.fake_session import FakeTelegramSession

TG_USER_ID = 770_000_001
CHAT_ID = 770_000_001

TG_USER = TgUser(id=TG_USER_ID, is_bot=False, first_name="Самат")
CHAT = Chat(id=CHAT_ID, type="private")

#: A second person, so a shared reminder can actually be shared (tech.md 22).
FRIEND_TG_USER_ID = 770_000_002

FRIEND_TG_USER = TgUser(id=FRIEND_TG_USER_ID, is_bot=False, first_name="Марат", username="marat")
FRIEND_CHAT = Chat(id=FRIEND_TG_USER_ID, type="private")


#: Everything the end-to-end run touches. The bot and the worker use separate
#: connections in production, so this suite commits for real and cleans up after
#: itself instead of hiding inside one transaction.
E2E_TABLES = (
    "delivery_actions",
    "deliveries",
    "occurrences",
    "reminder_recipients",
    "reminder_invites",
    "reminders",
    "categories",
    "users",
    "fsm_states",
)


async def truncate(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(f"TRUNCATE {', '.join(E2E_TABLES)} RESTART IDENTITY CASCADE")
        )


@pytest_asyncio.fixture
async def session_factory(engine):
    """Overrides the transactional factory: handlers and workers commit for real."""
    await truncate(engine)
    yield create_session_factory(engine)
    await truncate(engine)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        use_fake_bot=True,
        default_timezone="Europe/Moscow",
        default_language="ru",
        planner_horizon_hours=48,
        occurrence_ttl_minutes=180,
    )


@pytest.fixture
def telegram() -> FakeTelegramSession:
    return FakeTelegramSession()


@pytest_asyncio.fixture
async def context(settings, session_factory, engine, fake_clock, fake_bot, telegram):
    bot = Bot(token="42:TEST", session=telegram)
    yield AppContext(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        clock=fake_clock,
        gateway=fake_bot,
        bot=bot,
    )
    await bot.session.close()


@pytest.fixture
def dispatcher(context) -> Dispatcher:
    # Handler routers are module singletons; detach them so every test can
    # assemble its own dispatcher.
    for module in HANDLER_MODULES:
        module.router._parent_router = None
    return build_dispatcher(context)


class Feeder:
    """Feeds updates the way long polling would, one second apart."""

    def __init__(self, dispatcher: Dispatcher, bot: Bot, clock) -> None:
        self._dispatcher = dispatcher
        self._bot = bot
        self._clock = clock
        self._update_id = 0
        self._message_id = 5000
        self._user = TG_USER
        self._chat = CHAT

    def as_friend(self) -> "Feeder":
        """The same feeder speaking for the second person.

        A shared reminder needs two people, and they share the update counter
        so their updates keep arriving in the order the test wrote them.
        """
        other = Feeder(self._dispatcher, self._bot, self._clock)
        other._user = FRIEND_TG_USER
        other._chat = FRIEND_CHAT
        other._update_id = self._update_id
        other._message_id = self._message_id + 1000
        return other

    async def message(self, text: str) -> None:
        self._advance()
        self._message_id += 1
        update = Update(
            update_id=self._next_id(),
            message=Message(
                message_id=self._message_id,
                date=datetime.now(UTC),
                chat=self._chat,
                from_user=self._user,
                text=text,
            ),
        )
        await self._dispatcher.feed_update(self._bot, update)

    async def press(self, data: str) -> None:
        self._advance()
        self._message_id += 1
        update = Update(
            update_id=self._next_id(),
            callback_query=CallbackQuery(
                id=str(self._update_id),
                from_user=self._user,
                chat_instance="test",
                data=data,
                message=Message(
                    message_id=self._message_id,
                    date=datetime.now(UTC),
                    chat=self._chat,
                    from_user=self._user,
                    text="напоминание",
                ),
            ),
        )
        await self._dispatcher.feed_update(self._bot, update)

    def _advance(self) -> None:
        self._clock.advance(timedelta(seconds=1))

    def _next_id(self) -> int:
        self._update_id += 1
        return self._update_id


@pytest.fixture
def feed(dispatcher, context, fake_clock) -> Feeder:
    return Feeder(dispatcher, context.bot, fake_clock)


@pytest.fixture
def friend(feed) -> Feeder:
    return feed.as_friend()
