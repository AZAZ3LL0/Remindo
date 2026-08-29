"""Streak and completion rate rendering."""

from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.stats import StatsSummary


def render_stats(summary: StatsSummary, lang: Lang = DEFAULT_LANG) -> str:
    return "\n".join(
        [
            T("stats.title", lang),
            T(
                "stats.body",
                lang,
                streak=summary.current_streak,
                longest=summary.longest_streak,
                rate7=round(summary.last_7_days.rate * 100),
                done7=summary.last_7_days.completed,
                total7=summary.last_7_days.total,
                rate30=round(summary.last_30_days.rate * 100),
                done30=summary.last_30_days.completed,
                total30=summary.last_30_days.total,
            ),
        ]
    )
