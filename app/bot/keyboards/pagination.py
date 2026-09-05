"""Generic paginator. Arrows disappear at the edges."""

from collections.abc import Callable, Sequence
from typing import Literal, NamedTuple

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import NOOP_CALLBACK, PageCb
from app.bot.render.texts import DEFAULT_LANG, Lang, T

Scope = Literal["rem", "cat", "today"]


class PageItem(NamedTuple):
    text: str
    callback_data: str


def page_count(total: int, page_size: int) -> int:
    return max(1, -(-total // page_size))


def paginated_kb(
    items: Sequence[PageItem],
    scope: Scope,
    page: int,
    total_pages: int,
    lang: Lang = DEFAULT_LANG,
    *,
    nav: Callable[[int], CallbackData] | None = None,
) -> InlineKeyboardMarkup:
    """A page of rows plus the navigation row.

    `nav` builds the callback of an arrow for a screen whose pagination is not
    `PageCb`: the reminder list pages with `ListCb`, which also carries the
    category filter (tech.md 21.1). Left out, the arrows stay on `PageCb`.
    """
    build_nav = nav or (lambda target: PageCb(scope=scope, page=target))

    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=item.text, callback_data=item.callback_data)
    builder.adjust(1)

    navigation = InlineKeyboardBuilder()
    if page > 0:
        navigation.button(text=T("btn.prev", lang), callback_data=build_nav(page - 1))
    navigation.button(text=f"{page + 1}/{total_pages}", callback_data=NOOP_CALLBACK)
    if page + 1 < total_pages:
        navigation.button(text=T("btn.next", lang), callback_data=build_nav(page + 1))
    navigation.adjust(3)
    builder.attach(navigation)
    return builder.as_markup()
