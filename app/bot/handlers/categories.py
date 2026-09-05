"""/categories: the list, the card, creation, renaming and archiving."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import CatCb, PageCb, WizCb
from app.bot.filters import NOT_A_COMMAND
from app.bot.fsm.categories import CategoryForm
from app.bot.keyboards.categories import category_card_kb, category_list_kb, emoji_picker_kb
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pagination import page_count
from app.bot.keyboards.pickers import CATEGORY_PAGE_SIZE
from app.bot.render.categories import render_category_card, render_category_list
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import Category, User
from app.domain.categories import normalize_category_title
from app.domain.errors import CategoryExistsError, CategoryInUseError, ValidationError
from app.services.categories import CategoriesService

router = Router(name="categories")

#: FSM keys holding what the current form has collected so far.
TITLE_KEY = "title"
CATEGORY_ID_KEY = "category_id"

Screen = tuple[str, InlineKeyboardMarkup]


@router.message(Command("categories"))
async def handle_categories(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    await state.clear()
    text, keyboard = await _list_screen(session, clock, user, page=0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), PageCb.filter(F.scope == "cat"))
async def handle_page(
    query: CallbackQuery,
    callback_data: PageCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    text, keyboard = await _list_screen(session, clock, user, callback_data.page)
    await query.answer()
    await _show(query, text, keyboard)


@router.callback_query(StateFilter(None), CatCb.filter(F.action == "open"))
async def handle_open(
    query: CallbackQuery,
    callback_data: CatCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    text, keyboard = await _card_screen(session, clock, user, callback_data.category_id)
    await query.answer()
    await _show(query, text, keyboard)


@router.callback_query(StateFilter(None), WizCb.filter(F.step == "cat"))
async def handle_new(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if callback_data.value != "new":
        await query.answer()
        return
    await state.set_state(CategoryForm.title)
    await query.answer()
    await _show(query, T("categories.ask_title", user.language), None)


@router.message(CategoryForm.title, NOT_A_COMMAND)
async def handle_title(message: Message, user: User, state: FSMContext) -> None:
    try:
        title = normalize_category_title(message.text or "")
    except ValidationError:
        await message.answer(T("categories.title_invalid", user.language))
        return

    await state.update_data({TITLE_KEY: title})
    await state.set_state(CategoryForm.emoji)
    await message.answer(
        T("categories.ask_emoji", user.language), reply_markup=emoji_picker_kb(user.language)
    )


@router.callback_query(CategoryForm.emoji, WizCb.filter(F.step == "emoji"))
async def handle_emoji(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("categories.emoji_manual", user.language), None)
        return

    try:
        category = await _create(session, clock, user, state, callback_data.value)
    except ValidationError:
        await query.answer(T("categories.emoji_invalid", user.language), show_alert=True)
        return
    except CategoryExistsError:
        await query.answer(T("categories.duplicate", user.language), show_alert=True)
        return

    await query.answer(
        T("categories.created", user.language, emoji=category.emoji, title=category.title)
    )
    text, keyboard = await _card_screen(session, clock, user, category.id)
    await _show(query, text, keyboard)


@router.message(CategoryForm.emoji, NOT_A_COMMAND)
async def handle_emoji_text(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    try:
        category = await _create(session, clock, user, state, message.text or "")
    except ValidationError:
        await message.answer(T("categories.emoji_invalid", user.language))
        return
    except CategoryExistsError:
        await message.answer(T("categories.duplicate", user.language))
        return

    await message.answer(
        T("categories.created", user.language, emoji=category.emoji, title=category.title)
    )
    text, keyboard = await _card_screen(session, clock, user, category.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), CatCb.filter(F.action == "rename"))
async def handle_rename(
    query: CallbackQuery,
    callback_data: CatCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    category = await CategoriesService(session, clock).get_for_user(
        user.id, callback_data.category_id
    )
    if category.owner_id is None:
        await query.answer(T("categories.system_readonly", user.language), show_alert=True)
        return

    await state.set_state(CategoryForm.rename)
    await state.update_data({CATEGORY_ID_KEY: category.id})
    await query.answer()
    await _show(query, T("categories.ask_new_title", user.language), None)


@router.message(CategoryForm.rename, NOT_A_COMMAND)
async def handle_rename_text(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    data = await state.get_data()
    service = CategoriesService(session, clock)
    try:
        category = await service.rename(user.id, data[CATEGORY_ID_KEY], message.text or "")
    except ValidationError:
        await message.answer(T("categories.title_invalid", user.language))
        return
    except CategoryExistsError:
        await message.answer(T("categories.duplicate", user.language))
        return

    await state.clear()
    await message.answer(T("categories.renamed", user.language, title=category.title))
    text, keyboard = await _card_screen(session, clock, user, category.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), CatCb.filter(F.action == "archive"))
async def handle_archive(
    query: CallbackQuery,
    callback_data: CatCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    category = await CategoriesService(session, clock).get_for_user(
        user.id, callback_data.category_id
    )
    if category.owner_id is None:
        await query.answer(T("categories.system_readonly", user.language), show_alert=True)
        return

    await query.answer()
    await _show(
        query,
        T("categories.confirm_archive", user.language, title=category.title),
        confirm_kb("archive", category.id, user.language),
    )


@router.callback_query(StateFilter(None), CatCb.filter(F.action == "confirm_archive"))
async def handle_confirm_archive(
    query: CallbackQuery,
    callback_data: CatCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    service = CategoriesService(session, clock)
    try:
        result = await service.archive(user.id, callback_data.category_id)
    except CategoryInUseError:
        await query.answer(T("categories.in_use", user.language), show_alert=True)
        return

    if result.applied:
        await query.answer(T("categories.archived", user.language, title=result.category.title))
    else:
        await query.answer(T("categories.already_archived", user.language))

    text, keyboard = await _list_screen(session, clock, user, page=0)
    await _show(query, text, keyboard)


@router.callback_query(
    StateFilter(CategoryForm.title, CategoryForm.emoji, CategoryForm.rename),
    WizCb.filter(F.step == "cat"),
)
async def handle_cancel(
    query: CallbackQuery,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    await state.clear()
    await query.answer(T("categories.cancelled", user.language))
    text, keyboard = await _list_screen(session, clock, user, page=0)
    await _show(query, text, keyboard)


async def _create(
    session: AsyncSession, clock: Clock, user: User, state: FSMContext, emoji: str
) -> Category:
    """Finish the form. The state survives a rejected emoji, so retrying works."""
    data = await state.get_data()
    category = await CategoriesService(session, clock).create(user.id, data[TITLE_KEY], emoji)
    await state.clear()
    return category


async def _list_screen(session: AsyncSession, clock: Clock, user: User, page: int) -> Screen:
    service = CategoriesService(session, clock)
    categories = await service.list_for_user(user.id)
    total_pages = page_count(len(categories), CATEGORY_PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    chunk = categories[page * CATEGORY_PAGE_SIZE : (page + 1) * CATEGORY_PAGE_SIZE]
    return (
        render_category_list(chunk, page, CATEGORY_PAGE_SIZE, user.language),
        category_list_kb(chunk, page, total_pages, user.language),
    )


async def _card_screen(session: AsyncSession, clock: Clock, user: User, category_id: int) -> Screen:
    service = CategoriesService(session, clock)
    category = await service.get_for_user(user.id, category_id)
    counts = await service.counts_for([category])
    return (
        render_category_card(category, counts, user.language),
        category_card_kb(category.id, user.language, editable=category.owner_id is not None),
    )


async def _show(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Redraw the screen in place.

    A button that changes nothing produces an identical message, and Telegram
    answers that with `message is not modified`. The screen is already correct
    in that case, so the error is the expected outcome, not a failure.
    """
    if not isinstance(query.message, Message):
        return
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
