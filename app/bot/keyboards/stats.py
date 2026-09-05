"""Statistics screens (tech.md 23.4).

Handlers never build their own keyboards, so the category breakdown and the
single-category card are assembled here, on top of the shared primitives of
tech.md 9.

Neither screen carries a cancel button: statistics change nothing, so there is
nothing to cancel, and a category card returns through the button that opens
the whole picture again.
"""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import NO_CATEGORY_FILTER, StatCb
from app.bot.keyboards.pagination import PageItem, paginated_kb
from app.bot.render.texts import DEFAULT_LANG, Lang, T


def stats_kb(
    items: Sequence[PageItem], page: int, total_pages: int, lang: Lang = DEFAULT_LANG
) -> InlineKeyboardMarkup:
    """A page of the category breakdown.

    Navigation goes through `StatCb`, so the arrows keep the whole-picture
    slice they were pressed on (tech.md 23.3). The rows are the categories
    themselves: a screen that already lists them needs no second screen that
    lists them again.
    """
    return paginated_kb(
        items,
        "stats",
        page,
        total_pages,
        lang,
        nav=lambda target: StatCb(category_id=NO_CATEGORY_FILTER, page=target),
    )


def stats_card_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """One category's card: the way back to every category."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=T("btn.stats_all", lang),
        callback_data=StatCb(category_id=NO_CATEGORY_FILTER, page=0),
    )
    builder.adjust(1)
    return builder.as_markup()
