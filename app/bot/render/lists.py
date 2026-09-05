"""Numbered reminder list with the closest firing moment."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from app.bot.render.reminder import format_local
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category, Reminder
from app.domain.contracts import ReminderStatus


def render_reminder_list(
    items: Sequence[tuple[Reminder, Category, datetime | None]],
    page: int,
    total: int,
    tz: ZoneInfo,
    page_size: int = 8,
    lang: Lang = DEFAULT_LANG,
    filter_title: str | None = None,
) -> str:
    """The page as text. `filter_title` names the category in force, if any."""
    header = [] if filter_title is None else [T("list.filter", lang, title=filter_title)]

    if not items:
        return "\n".join([*header, T("list.empty", lang)])

    lines = [*header, T("list.title", lang, total=total)]
    for offset, (reminder, category, next_fire) in enumerate(items, start=1):
        # A paused reminder sits in the list next to active ones, so the row
        # says so: an unmarked row would lie about the status (tech.md 21.7).
        mark = "" if reminder.status is ReminderStatus.ACTIVE else T("list.paused_mark", lang)
        lines.append(
            T(
                "list.item",
                lang,
                index=page * page_size + offset,
                mark=mark,
                emoji=category.emoji,
                title=reminder.title,
                next_fire=format_local(next_fire, tz, lang),
            )
        )
    return "\n".join(lines)
