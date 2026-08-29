"""Done / snooze / skip. The message loses its buttons after a reaction."""

from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import ReactCb
from app.bot.render.reminder import format_local
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.domain.errors import NotFoundError, PermissionDeniedError
from app.services.reactions import ReactionsService

router = Router(name="reactions")

_APPLIED_TEXT = {
    "done": "react.done",
    "skip": "react.skipped",
}


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

    if not result.applied:
        await query.answer(T("react.already", user.language))
        return

    if result.action == "snooze":
        text = T(
            "react.snoozed",
            user.language,
            until=format_local(result.snoozed_until, ZoneInfo(user.timezone), user.language),
        )
    else:
        text = T(_APPLIED_TEXT[result.action], user.language)

    await query.answer(text)
    if isinstance(query.message, Message) and query.message.text is not None:
        await query.message.edit_text(f"{query.message.text}\n\n{text}", reply_markup=None)
