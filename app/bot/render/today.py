"""The day as a list of deliveries (tech.md 21.9)."""

from collections.abc import Sequence
from zoneinfo import ZoneInfo

from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.contracts import DeliveryStatus
from app.services.today import TodayEntry

#: What each delivery status looks like on the day. Statuses the user cannot
#: tell apart from a miss are drawn as one: `failed` and `blocked` mean the
#: message never arrived, which from the day's point of view is a miss.
_MARK_KEYS = {
    DeliveryStatus.PENDING: "today.mark_pending",
    DeliveryStatus.SNOOZED: "today.mark_pending",
    DeliveryStatus.SENT: "today.mark_pending",
    DeliveryStatus.DONE: "today.mark_done",
    DeliveryStatus.SKIPPED: "today.mark_skipped",
    DeliveryStatus.FAILED: "today.mark_missed",
    DeliveryStatus.BLOCKED: "today.mark_missed",
}


def render_today(
    entries: Sequence[TodayEntry], total: int, tz: ZoneInfo, lang: Lang = DEFAULT_LANG
) -> str:
    if not entries:
        return T("today.empty", lang)

    lines = [T("today.title", lang, total=total)]
    for entry in entries:
        lines.append(
            T(
                "today.item",
                lang,
                time=entry.fire_at.astimezone(tz).strftime("%H:%M"),
                mark=T(_MARK_KEYS[entry.status], lang),
                emoji=entry.emoji,
                title=entry.title,
            )
        )
    return "\n".join(lines)
