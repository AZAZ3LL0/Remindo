"""Shared access screens as text (tech.md 22.8)."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from app.bot.render.reminder import format_local, render_schedule_summary
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category, Reminder, User
from app.domain.contracts import RecipientRole
from app.domain.schedules import parse_schedule
from app.services.sharing import Participant, SharedReminder


def display_name(user: User | None, lang: Lang = DEFAULT_LANG) -> str:
    """What to call a recipient.

    `username` is nullable and `first_name` defaults to an empty string
    (tech.md 4.2), so there is always a last resort to fall back on.
    """
    if user is None:
        return T("share.unknown_user", lang)
    if user.username:
        return f"@{user.username}"
    return user.first_name.strip() or T("share.unknown_user", lang)


def render_share_menu(
    reminder: Reminder, participants: Sequence[Participant], lang: Lang = DEFAULT_LANG
) -> str:
    """The owner's access screen: who receives this, and who is still deciding."""
    watchers = [entry for entry in participants if entry.role is not RecipientRole.OWNER]
    if not watchers:
        recipients = T("share.recipients_none", lang)
    else:
        items = "\n".join(
            T(
                "share.recipient_item",
                lang,
                mark="" if entry.accepted else T("share.pending_mark", lang),
                name=display_name(entry.user, lang),
            )
            for entry in watchers
        )
        recipients = T("share.recipients", lang, items=items)
    return T("share.menu", lang, title=reminder.title, recipients=recipients)


def render_shared_card(
    reminder: Reminder,
    category: Category,
    owner: User | None,
    next_fire: datetime | None,
    tz: ZoneInfo,
    lang: Lang = DEFAULT_LANG,
) -> str:
    """What a watcher sees. No status and no snooze step: neither is theirs to
    change (tech.md 22.11), and a card offering them would invite a press that
    the service refuses."""
    return T(
        "share.card",
        lang,
        emoji=category.emoji,
        title=reminder.title,
        owner=display_name(owner, lang),
        schedule=render_schedule_summary(parse_schedule(reminder.schedule), lang),
        next_fire=format_local(next_fire, tz, lang),
    )


def render_shared_list(
    items: Sequence[tuple[SharedReminder, Category]],
    page: int,
    total: int,
    page_size: int = 8,
    lang: Lang = DEFAULT_LANG,
) -> str:
    if not items:
        return T("share.list_empty", lang)

    lines = [T("share.list_title", lang, total=total)]
    for offset, (shared, category) in enumerate(items, start=1):
        # An invitation still waiting for an answer sits next to the accepted
        # ones, so the row says so, the way a paused reminder does (tech.md 21.7).
        mark = "" if shared.accepted else T("share.pending_mark", lang)
        lines.append(
            T(
                "share.list_item",
                lang,
                index=page * page_size + offset,
                mark=mark,
                emoji=category.emoji,
                title=shared.reminder.title,
                owner=display_name(shared.owner, lang),
            )
        )
    return "\n".join(lines)
