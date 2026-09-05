"""Streak and completion rate rendering (tech.md 23.10)."""

from collections.abc import Mapping, Sequence
from zoneinfo import ZoneInfo

from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category
from app.domain.digest import DigestWindow
from app.domain.schedules import format_local_date
from app.domain.stats import CategoryStats, PeriodStats, StatsSummary


def percent(period: PeriodStats) -> int:
    return round(period.rate * 100)


def _body(summary: StatsSummary | CategoryStats, lang: Lang) -> str:
    return T(
        "stats.body",
        lang,
        streak=summary.current_streak,
        longest=summary.longest_streak,
        rate7=percent(summary.last_7_days),
        done7=summary.last_7_days.completed,
        total7=summary.last_7_days.total,
        rate30=percent(summary.last_30_days),
        done30=summary.last_30_days.completed,
        total30=summary.last_30_days.total,
    )


def render_stats(
    summary: StatsSummary,
    categories: Mapping[int, Category] | None = None,
    lang: Lang = DEFAULT_LANG,
) -> str:
    """The whole picture: the overall numbers, then the breakdown.

    A category with no outcome inside the history is absent rather than shown
    as a row of zeroes: the screen answers what the user has been doing, and a
    category they never touched is not an answer.
    """
    known = categories or {}
    lines = [T("stats.title", lang), _body(summary, lang), ""]

    rows = [entry for entry in summary.by_category if entry.category_id in known]
    if not rows:
        lines.append(T("stats.category_none", lang))
        return "\n".join(lines)

    items = "\n".join(
        T(
            "stats.category_item",
            lang,
            emoji=known[entry.category_id].emoji,
            title=known[entry.category_id].title,
            streak=entry.current_streak,
            rate7=percent(entry.last_7_days),
        )
        for entry in rows
    )
    lines.append(T("stats.by_category", lang, items=items))
    return "\n".join(lines)


def render_stats_card(summary: StatsSummary, category: Category, lang: Lang = DEFAULT_LANG) -> str:
    """One category's slice. The summary was already filtered to it, so the
    breakdown is not repeated: it would hold exactly one row, itself."""
    return "\n".join(
        [
            T("stats.card", lang, emoji=category.emoji, title=category.title),
            _body(summary, lang),
        ]
    )


def render_digest(
    summary: StatsSummary,
    window: DigestWindow,
    categories: Mapping[int, Category],
    tz: ZoneInfo,
    lang: Lang = DEFAULT_LANG,
) -> str:
    """The weekly message. Only the seven-day window: the digest reports the
    week it covers, and the monthly figure belongs to `/stats`."""
    week = summary.last_7_days
    lines = [
        T(
            "digest.title",
            lang,
            start=format_local_date(window.start.astimezone(tz).date()),
            end=format_local_date(window.end.astimezone(tz).date()),
        ),
        T(
            "digest.body",
            lang,
            done=week.completed,
            total=week.total,
            rate=percent(week),
            streak=summary.current_streak,
        ),
    ]
    lines.extend(_digest_rows(summary.by_category, categories, lang))
    return "\n".join(lines)


def _digest_rows(
    entries: Sequence[CategoryStats], categories: Mapping[int, Category], lang: Lang
) -> list[str]:
    return [
        T(
            "digest.category_item",
            lang,
            emoji=categories[entry.category_id].emoji,
            title=categories[entry.category_id].title,
            done=entry.last_7_days.completed,
            total=entry.last_7_days.total,
        )
        for entry in entries
        if entry.category_id in categories and entry.last_7_days.total
    ]
