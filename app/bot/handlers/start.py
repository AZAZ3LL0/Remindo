"""/start and timezone onboarding."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import WizCb
from app.bot.fsm.reminder_wizard import Onboarding
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.domain.errors import ValidationError
from app.services.onboarding import OnboardingService

router = Router(name="start")

POPULAR_TIMEZONES = (
    "Europe/Moscow",
    "Europe/Kaliningrad",
    "Europe/Samara",
    "Asia/Yekaterinburg",
    "Asia/Novosibirsk",
    "Asia/Vladivostok",
    "Europe/Berlin",
    "America/New_York",
)


def timezone_picker_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for zone in POPULAR_TIMEZONES:
        builder.button(text=zone, callback_data=WizCb(step="tz", value=zone))
    builder.adjust(2)
    return builder.as_markup()


@router.message(CommandStart())
async def handle_start(message: Message, user: User, state: FSMContext) -> None:
    await message.answer(T("start.greeting", user.language, name=user.first_name))
    await state.set_state(Onboarding.timezone)
    await message.answer(T("start.ask_timezone", user.language), reply_markup=timezone_picker_kb())


@router.callback_query(WizCb.filter(F.step == "tz"))
async def handle_timezone_choice(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    service = OnboardingService(session, clock, default_timezone, default_language)
    await service.set_timezone(user.id, callback_data.value)
    await state.clear()
    await query.answer()
    if query.message is not None:
        await query.message.answer(
            T("start.timezone_saved", user.language, timezone=callback_data.value)
        )


@router.message(Onboarding.timezone)
async def handle_timezone_text(
    message: Message,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    service = OnboardingService(session, clock, default_timezone, default_language)
    try:
        await service.set_timezone(user.id, (message.text or "").strip())
    except ValidationError:
        await message.answer(T("start.timezone_unknown", user.language))
        return
    await state.clear()
    await message.answer(T("start.timezone_saved", user.language, timezone=message.text))
