"""Done / snooze / skip. Every tap closes the message it came from."""

from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import ReactCb
from app.bot.render.reactions import render_outcome, render_reacted_message
from app.bot.render.texts import T
from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import User
from app.domain.errors import NotFoundError, PermissionDeniedError
from app.services.reactions import ReactionsService

router = Router(name="reactions")

_log = get_logger(__name__)


@router.callback_query(ReactCb.filter())
async def handle_reaction(
    query: CallbackQuery,
    callback_data: ReactCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    service = ReactionsService(session, clock)
    try:
        result = await service.react(callback_data.delivery_id, user.id, callback_data.action)
    except (NotFoundError, PermissionDeniedError):
        await query.answer(T("error.not_found", user.language), show_alert=True)
        return

    outcome = render_outcome(result, ZoneInfo(user.timezone), user.language)
    await query.answer(outcome)
    # A rejected tap closes its message too: the buttons are stale either way,
    # and delivery is at-least-once, so a duplicate message still carries them.
    await close_message(query, outcome)


async def close_message(query: CallbackQuery, outcome: str) -> None:
    """Drop the buttons and write the answer under the reminder.

    The reaction is already committed, so a refused edit is logged and dropped.
    Telegram refuses one for reasons that all predate the tap (message too old,
    text unchanged, chat gone), and reporting a failure here would tell the
    user their reaction did not count when it did.
    """
    message = query.message
    if not isinstance(message, Message):
        return
    try:
        if message.text is None:
            await message.edit_reply_markup(reply_markup=None)
        else:
            # `html_text` rebuilds the markup the dispatcher sent and escapes
            # everything else, so a title containing `<` survives the redraw.
            await message.edit_text(
                render_reacted_message(message.html_text, outcome),
                parse_mode="HTML",
                reply_markup=None,
            )
    except TelegramAPIError as error:
        _log.warning(
            "reaction.edit_failed",
            message_id=message.message_id,
            error=type(error).__name__,
        )
