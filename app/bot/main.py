"""Entry point of the `bot` process. It accepts updates and never sends reminders."""

import asyncio

from aiogram import Dispatcher

from app.bot.fsm.storage import SQLAlchemyStorage
from app.bot.handlers import (
    categories,
    errors,
    lists,
    manage,
    reactions,
    reminders,
    share,
    start,
    stats,
)
from app.bot.handlers import (
    settings as settings_handlers,
)
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.throttle import ThrottleMiddleware
from app.bot.middlewares.user import CurrentUserMiddleware
from app.core.di import AppContext, build_context
from app.core.logging import get_logger

_log = get_logger(__name__)


def build_dispatcher(context: AppContext) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=SQLAlchemyStorage(context.session_factory),
        clock=context.clock,
        gateway=context.gateway,
        default_timezone=context.settings.default_timezone,
        default_language=context.settings.default_language,
        bot_username=context.settings.bot_username,
    )

    db_middleware = DbSessionMiddleware(context.session_factory)
    user_middleware = CurrentUserMiddleware(
        context.clock,
        context.settings.default_timezone,
        context.settings.default_language,
    )
    throttle = ThrottleMiddleware(context.clock)

    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.middleware(db_middleware)
        observer.middleware(throttle)
        observer.middleware(user_middleware)

    dispatcher.include_routers(
        start.router,
        settings_handlers.router,
        categories.router,
        reminders.router,
        manage.router,
        share.router,
        reactions.router,
        lists.router,
        stats.router,
        errors.router,
    )
    return dispatcher


async def run() -> None:
    context = build_context()
    dispatcher = build_dispatcher(context)
    try:
        if context.bot is None:
            _log.info("bot.fake_mode", reason="USE_FAKE_BOT is on, polling disabled")
            await asyncio.Event().wait()
            return
        await dispatcher.start_polling(context.bot)
    finally:
        await context.shutdown()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
