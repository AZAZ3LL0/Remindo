"""Entry point of the `bot` process. It accepts updates and never sends reminders."""

import asyncio
from typing import Final

from aiogram import Dispatcher

from app.bot.commands import menu_for
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
    help as help_handlers,
)
from app.bot.handlers import (
    settings as settings_handlers,
)
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.throttle import ThrottleMiddleware
from app.bot.middlewares.user import CurrentUserMiddleware
from app.bot.render.texts import SUPPORTED_LANGS
from app.core.di import AppContext, build_context
from app.core.logging import get_logger

_log = get_logger(__name__)

#: Routers, in the order the dispatcher consults them. The catch-all in `help`
#: comes last on purpose, and that is a safety condition rather than a
#: preference: every text handler is state-filtered and lives in a router above,
#: so the catch-all cannot swallow the wizard's input (tech.md 25.4).
HANDLER_MODULES: Final = (
    start,
    settings_handlers,
    categories,
    reminders,
    manage,
    share,
    reactions,
    lists,
    stats,
    help_handlers,
    errors,
)


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

    dispatcher.include_routers(*(module.router for module in HANDLER_MODULES))
    return dispatcher


async def publish_commands(context: AppContext) -> None:
    """Offer the command menu, once per supported language.

    A refusal is logged and swallowed: a bot that will not boot because a
    command caption failed to update is worse than one with a stale caption
    (tech.md 25.3).
    """
    for lang in SUPPORTED_LANGS:
        try:
            await context.gateway.set_commands(menu_for(lang), lang)
        except Exception as error:
            _log.error("bot.commands_failed", lang=lang, error=type(error).__name__)


async def run() -> None:
    context = build_context()
    dispatcher = build_dispatcher(context)
    await publish_commands(context)
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
