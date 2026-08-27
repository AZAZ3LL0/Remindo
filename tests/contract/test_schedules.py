"""Schedule payload contract (tech.md 5)."""

from datetime import datetime, time

import pytest
from pydantic import ValidationError

from app.domain.contracts import ScheduleKind
from app.domain.schedules import dump_schedule, parse_schedule

VALID_PAYLOADS = [
    {"kind": "once", "at": "2026-09-01T07:30"},
    {
        "kind": "interval",
        "every_minutes": 120,
        "window_start": "09:00",
        "window_end": "21:00",
    },
    {"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1},
    {"kind": "weekly", "times": ["07:30"], "weekdays": [1, 3, 5]},
    {"kind": "monthly", "times": ["10:00"], "days": [1, 15], "on_missing_day": "last_day"},
]


@pytest.mark.parametrize("payload", VALID_PAYLOADS)
def test_documented_payloads_round_trip(payload):
    assert dump_schedule(parse_schedule(payload)) == payload


@pytest.mark.parametrize("payload", VALID_PAYLOADS)
def test_kind_is_a_known_discriminator(payload):
    assert ScheduleKind(parse_schedule(payload).kind) is ScheduleKind(payload["kind"])


def test_times_are_sorted_and_deduplicated():
    schedule = parse_schedule({"kind": "daily", "times": ["20:00", "08:00", "08:00"]})
    assert schedule.times == [time(8, 0), time(20, 0)]
    assert dump_schedule(schedule)["times"] == ["08:00", "20:00"]


def test_weekdays_and_days_are_normalised():
    weekly = parse_schedule({"kind": "weekly", "times": ["07:30"], "weekdays": [5, 1, 5]})
    monthly = parse_schedule({"kind": "monthly", "times": ["10:00"], "days": [15, 1, 15]})
    assert weekly.weekdays == [1, 5]
    assert monthly.days == [1, 15]


def test_window_may_cross_midnight():
    schedule = parse_schedule(
        {"kind": "interval", "every_minutes": 60, "window_start": "22:00", "window_end": "02:00"}
    )
    assert schedule.window_start > schedule.window_end


def test_once_keeps_wall_clock_and_stays_naive():
    schedule = parse_schedule({"kind": "once", "at": "2026-09-01T07:30"})
    assert schedule.at == datetime(2026, 9, 1, 7, 30)
    assert schedule.at.tzinfo is None


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "interval", "every_minutes": 4, "window_start": "09:00", "window_end": "21:00"},
        {
            "kind": "interval",
            "every_minutes": 1441,
            "window_start": "09:00",
            "window_end": "21:00",
        },
        {"kind": "daily", "times": []},
        {"kind": "daily", "times": [f"{hour:02d}:00" for hour in range(13)]},
        {"kind": "daily", "times": ["8:00"]},
        {"kind": "daily", "times": ["24:00"]},
        {"kind": "weekly", "times": ["07:30"], "weekdays": [0]},
        {"kind": "weekly", "times": ["07:30"], "weekdays": [8]},
        {"kind": "weekly", "times": ["07:30"], "weekdays": []},
        {"kind": "monthly", "times": ["10:00"], "days": [32]},
        {"kind": "monthly", "times": ["10:00"], "days": [1], "on_missing_day": "explode"},
        {"kind": "once", "at": "2026-09-01T07:30:15"},
        {"kind": "once", "at": "2026-09-01T07:30+03:00"},
        {"kind": "daily", "times": ["08:00"], "unexpected": 1},
        {"kind": "unknown", "times": ["08:00"]},
    ],
)
def test_invalid_payloads_are_rejected(payload):
    with pytest.raises(ValidationError):
        parse_schedule(payload)


def test_schedules_are_immutable():
    schedule = parse_schedule({"kind": "daily", "times": ["08:00"]})
    with pytest.raises(ValidationError):
        schedule.every_n_days = 3
