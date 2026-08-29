"""Category screens. Handlers never build their own keyboards."""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import CatCb, PageCb, WizCb
from app.bot.keyboards.pagination import PageItem, paginated_kb
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category

#: `WizCb.value` atoms that are commands rather than data. No emoji preset may
#: collide with them; the contract test holds that line.
RESERVED_VALUES: frozenset[str] = frozenset({"new", "cancel", "man"})

#: Emoji offered when a category is created. Anything else arrives as manual
#: input, so the list stays short instead of complete.
EMOJI_PRESETS: tuple[str, ...] = (
    "\U0001f4a1",
    "\U0001f4da",
    "\U0001f4bc",
    "\U0001f9f9",
    "\U0001f6d2",
    "\U0001f43e",
    "\U0001f3b5",
    "\U0001f9d8",
    "\U0001f4b0",
    "\U0001f697",
    "\U0001f331",
    "\U0001f381",
)


def _back_button(builder: InlineKeyboardBuilder, lang: Lang) -> None:
    builder.button(text=T("btn.back", lang), callback_data=PageCb(scope="cat", page=0))


def category_list_kb(
    categories: Sequence[Category],
    page: int,
    total_pages: int,
    lang: Lang = DEFAULT_LANG,
) -> InlineKeyboardMarkup:
    """One page of categories on top of the shared paginator, plus creation."""
    items = [
        PageItem(
            text=f"{category.emoji} {category.title}",
            callback_data=CatCb(category_id=category.id, action="open").pack(),
        )
        for category in categories
    ]
    builder = InlineKeyboardBuilder.from_markup(paginated_kb(items, "cat", page, total_pages, lang))
    builder.row(
        InlineKeyboardButton(
            text=T("btn.new_category", lang),
            callback_data=WizCb(step="cat", value="new").pack(),
        )
    )
    return builder.as_markup()


def category_card_kb(
    category_id: int, lang: Lang = DEFAULT_LANG, *, editable: bool
) -> InlineKeyboardMarkup:
    """System presets are read-only, so they get navigation and nothing else."""
    builder = InlineKeyboardBuilder()
    if editable:
        builder.button(
            text=T("btn.rename", lang),
            callback_data=CatCb(category_id=category_id, action="rename"),
        )
        builder.button(
            text=T("btn.archive", lang),
            callback_data=CatCb(category_id=category_id, action="archive"),
        )
    _back_button(builder, lang)
    builder.adjust(2, 1)
    return builder.as_markup()


def emoji_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for emoji in EMOJI_PRESETS:
        builder.button(text=emoji, callback_data=WizCb(step="emoji", value=emoji))
    builder.button(text=T("btn.manual_input", lang), callback_data=WizCb(step="emoji", value="man"))
    builder.button(text=T("btn.cancel", lang), callback_data=WizCb(step="cat", value="cancel"))
    builder.adjust(6, 6, 2)
    return builder.as_markup()
