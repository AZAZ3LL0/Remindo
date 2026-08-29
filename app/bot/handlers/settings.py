"""/settings: timezone, language and quiet hours."""

from datetime import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import WizCb
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.services.onboarding import OnboardingService

router = Router(name="settings")

#: Offered quiet interval, local wall clock.
DEFAULT_QUIET = (time(23, 0), time(7, 0))


def settings_kb(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="ru / en",
        callback_data=WizCb(step="lang", value="en" if user.language == "ru" else "ru"),
    )
    builder.button(
        text=T("settings.quiet_off", user.language) if user.quiet_start else "23:00-07:00",
        callback_data=WizCb(step="quiet", value="off" if user.quiet_start else "on"),
    )
    builder.adjust(2)
    return builder.as_markup()


def render_settings(user: User) -> str:
    quiet = (
        f"{user.quiet_start:%H:%M}-{user.quiet_end:%H:%M}"
        if user.quiet_start and user.quiet_end
        else T("settings.quiet_off", user.language)
    )
    return T(
        "settings.title",
        user.language,
        timezone=user.timezone,
        language=user.language,
        quiet=quiet,
    )


@router.message(Command("settings"))
async def handle_settings(message: Message, user: User) -> None:
    await message.answer(render_settings(user), reply_markup=settings_kb(user))


@router.callback_query(WizCb.filter(F.step == "lang"))
async def handle_language(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    default_timezone: str,
    default_language: str,
) -> None:
    service = OnboardingService(session, clock, default_timezone, default_language)
    updated = await service.set_language(user.id, callback_data.value)
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.edit_text(render_settings(updated), reply_markup=settings_kb(updated))


@router.callback_query(WizCb.filter(F.step == "quiet"))
async def handle_quiet_hours(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    default_timezone: str,
    default_language: str,
) -> None:
    service = OnboardingService(session, clock, default_timezone, default_language)
    quiet = DEFAULT_QUIET if callback_data.value == "on" else (None, None)
    updated = await service.set_quiet_hours(user.id, quiet[0], quiet[1])
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.edit_text(render_settings(updated), reply_markup=settings_kb(updated))
