"""Last line of defence. A user never sees a traceback."""

from aiogram import Router
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.bot.render.texts import DEFAULT_LANG, T
from app.core.logging import get_logger
from app.domain.errors import DomainError, NotFoundError, PermissionDeniedError

router = Router(name="errors")

_log = get_logger(__name__)


@router.errors()
async def handle_error(event: ErrorEvent) -> bool:
    error = event.exception
    key = (
        "error.not_found"
        if isinstance(error, NotFoundError | PermissionDeniedError)
        else "error.generic"
    )

    _log.error(
        "handler.failed",
        error=type(error).__name__,
        domain=isinstance(error, DomainError),
        exc_info=not isinstance(error, DomainError),
    )

    target = event.update.message or (
        event.update.callback_query.message if event.update.callback_query else None
    )
    if isinstance(event.update.callback_query, CallbackQuery):
        await event.update.callback_query.answer(T(key, DEFAULT_LANG))
    elif isinstance(target, Message):
        await target.answer(T(key, DEFAULT_LANG))
    return True
