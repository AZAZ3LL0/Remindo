"""Reminder card and the reminder message the dispatcher sends."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category, Reminder
from app.domain.contracts import ReminderStatus

_STATUS_KEYS = {
    ReminderStatus.ACTIVE: "status.active",
    ReminderStatus.PAUSED: "status.paused",
    ReminderStatus.ARCHIVED: "status.archived",
}


def format_local(moment: datetime | None, tz: ZoneInfo, lang: Lang = DEFAULT_LANG) -> str:
    if moment is None:
        return T("reminder.no_next_fire", lang)
    return moment.astimezone(tz).strftime("%d.%m %H:%M")


def render_reminder_message(
    reminder: Reminder, category: Category, fire_at: datetime, tz: ZoneInfo, lang: Lang
) -> str:
    return T(
        "reminder.message",
        lang,
        emoji=category.emoji,
        title=reminder.title,
        time=format_local(fire_at, tz, lang),
    )


def render_reminder_card(
    reminder: Reminder,
    category: Category,
    next_fire: datetime | None,
    tz: ZoneInfo,
    lang: Lang = DEFAULT_LANG,
) -> str:
    return T(
        "reminder.card",
        lang,
        emoji=category.emoji,
        title=reminder.title,
        status=T(_STATUS_KEYS[reminder.status], lang),
        next_fire=format_local(next_fire, tz, lang),
    )
