"""Streaks and completion rates."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.contracts import ActionKind
from app.domain.stats import ActionRecord, PeriodStats, build_summary
from tests.unit.strategies import timezones

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
CASES = settings(max_examples=150, deadline=None)

records = st.lists(
    st.builds(
        ActionRecord,
        happened_at=st.integers(min_value=0, max_value=40 * 24 * 60).map(
            lambda minutes: NOW - timedelta(minutes=minutes)
        ),
        kind=st.sampled_from(list(ActionKind)),
        category_id=st.integers(min_value=1, max_value=4),
    ),
    max_size=60,
)


@CASES
@given(history=records, tz=timezones)
def test_rates_stay_inside_the_unit_interval(history, tz):
    summary = build_summary(history, tz, NOW)
    for period in (summary.last_7_days, summary.last_30_days):
        assert 0 <= period.completed <= period.total
        assert 0.0 <= period.rate <= 1.0


@CASES
@given(history=records, tz=timezones)
def test_current_streak_never_exceeds_the_longest(history, tz):
    summary = build_summary(history, tz, NOW)
    assert 0 <= summary.current_streak <= summary.longest_streak


@CASES
@given(history=records, tz=timezones, seed=st.integers(min_value=0, max_value=10_000))
def test_order_of_records_does_not_matter(history, tz, seed):
    shuffled = sorted(history, key=lambda record: (hash(record.happened_at) + seed) % 97)
    assert build_summary(history, tz, NOW) == build_summary(shuffled, tz, NOW)


@CASES
@given(history=records, tz=timezones)
def test_snoozes_are_not_outcomes(history, tz):
    """A snooze postpones the reminder, it does not resolve it."""
    with_snoozes = [*history, ActionRecord(NOW - timedelta(hours=1), ActionKind.SNOOZE)]
    assert build_summary(history, tz, NOW) == build_summary(with_snoozes, tz, NOW)


def test_streak_counts_consecutive_days_with_a_completion():
    tz = ZoneInfo("Europe/Moscow")
    history = [ActionRecord(NOW - timedelta(days=offset), ActionKind.DONE) for offset in range(4)]
    summary = build_summary(history, tz, NOW)
    assert summary.current_streak == 4
    assert summary.longest_streak == 4


def test_a_gap_breaks_the_current_streak_but_not_the_record():
    tz = ZoneInfo("Europe/Moscow")
    history = [
        ActionRecord(NOW - timedelta(days=offset), ActionKind.DONE) for offset in (0, 1, 4, 5, 6, 7)
    ]
    summary = build_summary(history, tz, NOW)
    assert summary.current_streak == 2
    assert summary.longest_streak == 4


def test_missing_today_does_not_break_the_streak_yet():
    tz = ZoneInfo("Europe/Moscow")
    history = [ActionRecord(NOW - timedelta(days=offset), ActionKind.DONE) for offset in (1, 2, 3)]
    assert build_summary(history, tz, NOW).current_streak == 3


def test_completion_rate_counts_only_outcomes():
    tz = ZoneInfo("UTC")
    history = [
        ActionRecord(NOW - timedelta(hours=1), ActionKind.DONE),
        ActionRecord(NOW - timedelta(hours=2), ActionKind.SKIP),
        ActionRecord(NOW - timedelta(hours=3), ActionKind.AUTO_EXPIRE),
        ActionRecord(NOW - timedelta(hours=4), ActionKind.SNOOZE),
    ]
    summary = build_summary(history, tz, NOW)
    assert (summary.last_7_days.completed, summary.last_7_days.total) == (1, 3)


def test_empty_history_is_a_zero_summary():
    summary = build_summary([], ZoneInfo("UTC"), NOW)
    assert summary.current_streak == 0
    assert summary.last_30_days.rate == 0.0
    assert summary.by_category == ()


@CASES
@given(history=records, tz=timezones)
def test_the_breakdown_accounts_for_every_outcome(history, tz):
    """Rule 4: each outcome belongs to exactly one category, so the parts add up."""
    summary = build_summary(history, tz, NOW)
    for window in ("last_7_days", "last_30_days"):
        parts = [getattr(entry, window) for entry in summary.by_category]
        whole = getattr(summary, window)
        assert sum(part.total for part in parts) == whole.total
        assert sum(part.completed for part in parts) == whole.completed


@CASES
@given(history=records, tz=timezones)
def test_a_category_streak_never_beats_the_whole(history, tz):
    """Rule 5: a day credited to a category is credited to the total as well."""
    summary = build_summary(history, tz, NOW)
    for entry in summary.by_category:
        assert entry.current_streak <= summary.current_streak
        assert entry.longest_streak <= summary.longest_streak
        assert 0 <= entry.current_streak <= entry.longest_streak


@CASES
@given(history=records, tz=timezones)
def test_the_breakdown_is_ordered_and_holds_only_categories_with_outcomes(history, tz):
    summary = build_summary(history, tz, NOW)
    ids = [entry.category_id for entry in summary.by_category]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))

    expected = {record.category_id for record in history if record.kind is not ActionKind.SNOOZE}
    assert set(ids) == expected


@CASES
@given(history=records, tz=timezones, seed=st.integers(min_value=0, max_value=10_000))
def test_the_breakdown_does_not_depend_on_journal_order(history, tz, seed):
    shuffled = sorted(history, key=lambda record: (hash(record.happened_at) + seed) % 97)
    assert (
        build_summary(history, tz, NOW).by_category == build_summary(shuffled, tz, NOW).by_category
    )


def test_a_category_slice_matches_the_summary_of_that_category_alone():
    """The breakdown is a filter, not a second way of counting."""
    tz = ZoneInfo("Europe/Moscow")
    history = [
        ActionRecord(NOW - timedelta(days=1), ActionKind.DONE, 7),
        ActionRecord(NOW - timedelta(days=2), ActionKind.SKIP, 7),
        ActionRecord(NOW - timedelta(days=1), ActionKind.DONE, 9),
    ]
    whole = build_summary(history, tz, NOW)
    alone = build_summary([r for r in history if r.category_id == 7], tz, NOW)
    entry = next(item for item in whole.by_category if item.category_id == 7)

    assert (entry.current_streak, entry.longest_streak) == (
        alone.current_streak,
        alone.longest_streak,
    )
    assert entry.last_7_days == alone.last_7_days == PeriodStats(completed=1, total=2)
