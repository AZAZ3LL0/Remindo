"""Dependency wiring for the `bot` and `worker` processes."""

from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.db.session import create_engine, create_session_factory
from app.gateways.bot_gateway import AiogramBotGateway, BotGateway
from app.gateways.fakes import FakeBotGateway


@dataclass
class AppContext:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    clock: Clock
    gateway: BotGateway
    bot: Bot | None

    async def shutdown(self) -> None:
        if self.bot is not None:
            await self.bot.session.close()
        await self.engine.dispose()


def build_context(settings: Settings | None = None) -> AppContext:
    settings = settings or get_settings()
    setup_logging(settings.log_level, json_output=settings.env == "prod")

    engine = create_engine(settings.database_url, echo=False)
    session_factory = create_session_factory(engine)
    clock: Clock = SystemClock()

    bot: Bot | None = None
    gateway: BotGateway
    if settings.use_fake_bot:
        # Dev and tests run without a real token; the fake enforces the contract.
        gateway = FakeBotGateway()
    else:
        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode="HTML"),
        )
        gateway = AiogramBotGateway(bot)

    return AppContext(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        clock=clock,
        gateway=gateway,
        bot=bot,
    )
