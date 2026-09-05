"""/start and the first-contact timezone question."""

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import SetCb
from app.bot.fsm.onboarding import Onboarding
from app.bot.handlers.share import follow_invite, pending_invite_screen
from app.bot.keyboards.settings import settings_kb, timezone_picker_kb
from app.bot.render.settings import render_settings
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.domain.errors import ValidationError
from app.services.onboarding import OnboardingService

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(
    message: Message,
    command: CommandObject,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    """Greet, and ask for a timezone only while the user has never answered.

    A start payload is an invitation (tech.md 22.5). It is resolved before the
    greeting so the recipient row exists either way, but its screen waits until
    the timezone is answered: without one the reminder has no local time to be
    shown in.
    """
    invitation = await follow_invite(command.args, user, session, clock) if command.args else None
    if invitation is not None and invitation.notice is not None:
        await message.answer(invitation.notice)

    if user.onboarded_at is None:
        await state.set_state(Onboarding.timezone)
        await message.answer(T("start.greeting", user.language, name=user.first_name))
        await message.answer(
            T("start.ask_timezone", user.language),
            reply_markup=timezone_picker_kb(user.language, with_back=False),
        )
        return

    await state.clear()
    if invitation is not None and invitation.screen is not None:
        text, keyboard = invitation.screen
        await message.answer(text, reply_markup=keyboard)
        return

    await message.answer(T("start.welcome_back", user.language, name=user.first_name))
    await message.answer(render_settings(user), reply_markup=settings_kb(user.language))


@router.callback_query(Onboarding.timezone, SetCb.filter(F.field == "tz"))
async def handle_onboarding_timezone(
    query: CallbackQuery,
    callback_data: SetCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    if callback_data.value == "manual":
        await query.answer()
        await _reply(query, T("start.timezone_manual", user.language))
        return

    service = OnboardingService(session, clock, default_timezone, default_language)
    updated = await service.set_timezone(user.id, callback_data.value)
    await state.clear()
    await query.answer(T("settings.saved", updated.language))
    if isinstance(query.message, Message):
        await _finish_onboarding(query.message, updated, session, clock)


@router.message(Onboarding.timezone)
async def handle_onboarding_timezone_text(
    message: Message,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    """Manual IANA input. A typo keeps the state, so the user can try again."""
    service = OnboardingService(session, clock, default_timezone, default_language)
    try:
        updated = await service.set_timezone(user.id, message.text or "")
    except ValidationError:
        await message.answer(T("start.timezone_unknown", user.language))
        return

    await state.clear()
    await _finish_onboarding(message, updated, session, clock)


async def _finish_onboarding(
    message: Message, user: User, session: AsyncSession, clock: Clock
) -> None:
    """Confirm the timezone, then answer the question the user came with.

    An invitee usually meets the bot through a deep link, so the invitation
    waiting in the database is shown here rather than the settings screen
    (tech.md 22.5).
    """
    await message.answer(T("start.timezone_saved", user.language, timezone=user.timezone))
    screen = await pending_invite_screen(user, session, clock)
    if screen is not None:
        text, keyboard = screen
        await message.answer(text, reply_markup=keyboard)
        return
    await message.answer(render_settings(user), reply_markup=settings_kb(user.language))


async def _reply(query: CallbackQuery, text: str) -> None:
    """Answer next to the pressed button; the picker message stays as history."""
    if isinstance(query.message, Message):
        await query.message.answer(text)
