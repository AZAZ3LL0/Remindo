"""Category list and card text."""

from collections.abc import Mapping, Sequence

from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category


def render_category_list(
    categories: Sequence[Category], page: int, page_size: int, lang: Lang = DEFAULT_LANG
) -> str:
    """Numbered page. Numbering continues across pages, it does not restart."""
    if not categories:
        return T("categories.empty", lang)
    lines = [
        T(
            "categories.item",
            lang,
            index=page * page_size + offset,
            emoji=item.emoji,
            title=item.title,
        )
        for offset, item in enumerate(categories, start=1)
    ]
    return "\n".join([T("categories.title", lang), *lines])


def render_category_card(
    category: Category, counts: Mapping[int, int], lang: Lang = DEFAULT_LANG
) -> str:
    kind = "categories.kind_system" if category.owner_id is None else "categories.kind_own"
    return T(
        "categories.card",
        lang,
        emoji=category.emoji,
        title=category.title,
        code=category.code,
        kind=T(kind, lang),
        reminders=counts.get(category.id, 0),
    )
