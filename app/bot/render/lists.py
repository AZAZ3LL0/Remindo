"""Numbered reminder list with the closest firing moment."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from app.bot.render.reminder import format_local
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category, Reminder


def render_reminder_list(
    items: Sequence[tuple[Reminder, Category, datetime | None]],
    page: int,
    total: int,
    tz: ZoneInfo,
    page_size: int = 8,
    lang: Lang = DEFAULT_LANG,
) -> str:
    if not items:
        return T("list.empty", lang)

    lines = [T("list.title", lang, total=total)]
    for offset, (reminder, category, next_fire) in enumerate(items, start=1):
        lines.append(
            T(
                "list.item",
                lang,
                index=page * page_size + offset,
                emoji=category.emoji,
                title=reminder.title,
                next_fire=format_local(next_fire, tz, lang),
            )
        )
    return "\n".join(lines)
