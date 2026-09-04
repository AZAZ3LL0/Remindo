"""Wizard contract (tech.md 18): callback atoms, keyboards, schedule payloads.

The seam is `FakeBotGateway.validate_keyboard`: a keyboard it rejects is a
keyboard Telegram would reject too.
"""

from datetime import date, datetime

import pytest

from app.bot.callbacks import WizCb, pack_wall_time, pack_window, unpack_wall_time, unpack_window
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pickers import (
    INTERVAL_PRESETS,
    SELECTED_MARK,
    WINDOW_PRESETS,
)
from app.bot.keyboards.wizard import (
    DAILY_TIME_PRESETS,
    MISSING_DAY_ATOMS,
    RESERVED_VALUES,
    WIZARD_SCHEDULE_KINDS,
    daily_times_kb,
    date_picker_kb,
    interval_kb,
    missing_day_kb,
    monthday_kb,
    once_time_kb,
    schedule_kind_kb,
    weekly_days_kb,
    window_kb,
)
from app.domain.contracts import ScheduleKind
from app.domain.reminders import parse_user_window
from app.domain.schedules import (
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    MONTH_DAYS_MAX_LENGTH,
    TIMES_MAX_LENGTH,
    WEEKDAYS_MAX_LENGTH,
    WINDOW_ATOM_LENGTH,
    dump_schedule,
    format_local_date,
    parse_hhmm,
    parse_local_date,
    parse_schedule,
)
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard

#: Longest date the wizard can put in a callback, a year out with a leap day.
LONGEST_DATE = "2028-12-31"

ALL_MONTH_DAYS = tuple(range(1, MONTH_DAYS_MAX_LENGTH + 1))
ALL_WEEKDAYS = tuple(range(1, WEEKDAYS_MAX_LENGTH + 1))

#: Every screen the wizard can put in front of a user.
KEYBOARDS = {
    "kind": schedule_kind_kb("ru"),
    "date": date_picker_kb("ru"),
    "once_time": once_time_kb("ru"),
    "daily_times_empty": daily_times_kb([], "ru"),
    "daily_times_all": daily_times_kb(DAILY_TIME_PRESETS, "ru"),
    "weekdays_empty": weekly_days_kb([], "ru"),
    "weekdays_all": weekly_days_kb(ALL_WEEKDAYS, "ru"),
    "month_days_empty": monthday_kb([], "ru"),
    "month_days_all": monthday_kb(ALL_MONTH_DAYS, "ru"),
    "missing_day": missing_day_kb("ru"),
    "interval": interval_kb("ru"),
    "window": window_kb("ru"),
    "confirm_create": confirm_kb("create", 0, "ru"),
}


@pytest.mark.parametrize("keyboard", KEYBOARDS.values(), ids=KEYBOARDS.keys())
def test_keyboard_passes_the_outgoing_contract(keyboard):
    validate_keyboard(keyboard)


WIZARD_ATOMS = [
    ("kind", "once"),
    ("kind", "daily"),
    ("kind", "weekly"),
    ("kind", "monthly"),
    ("kind", "interval"),
    ("wday", "7"),
    ("wday", "ok"),
    ("mday", str(MONTH_DAYS_MAX_LENGTH)),
    ("mday", "ok"),
    ("miss", "last"),
    ("miss", "skip"),
    ("every", str(INTERVAL_MAX_MINUTES)),
    ("every", "man"),
    ("window", "00000000"),
    ("window", "23592359"),
    ("window", "man"),
    ("date", "today"),
    ("date", "tmrw"),
    ("date", LONGEST_DATE),
    ("date", "man"),
    ("at", "2359"),
    ("at", "man"),
    ("time", "0730"),
    ("time", "man"),
    ("times", "ok"),
    ("confirm", "yes"),
    ("confirm", "no"),
]


@pytest.mark.parametrize(("step", "value"), WIZARD_ATOMS, ids=lambda part: str(part))
def test_wizard_atom_survives_a_round_trip_inside_the_limit(step, value):
    packed = WizCb(step=step, value=value).pack()

    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    unpacked = WizCb.unpack(packed)
    assert (unpacked.step, unpacked.value) == (step, value)


@pytest.mark.parametrize("preset", DAILY_TIME_PRESETS)
def test_a_time_preset_travels_packed_and_comes_back_whole(preset):
    """`:` is the callback separator, so the atom drops it and restores it."""
    packed = WizCb(step="time", value=pack_wall_time(preset)).pack()

    assert unpack_wall_time(WizCb.unpack(packed).value) == preset


def test_no_preset_collides_with_a_reserved_command():
    """Reserved atoms are commands; no preset value may shadow one."""
    packed = {pack_wall_time(preset) for preset in DAILY_TIME_PRESETS}
    packed |= {pack_window(start, end) for start, end in WINDOW_PRESETS}
    packed |= {str(minutes) for minutes in INTERVAL_PRESETS}
    packed |= {str(day) for day in (*ALL_WEEKDAYS, *ALL_MONTH_DAYS)}

    assert not RESERVED_VALUES.intersection(packed)


@pytest.mark.parametrize(("start", "end"), WINDOW_PRESETS, ids=lambda part: str(part))
def test_a_window_preset_travels_packed_and_comes_back_whole(start, end):
    """Two wall-clock times, one atom, no separator (tech.md 19.1)."""
    packed = WizCb(step="window", value=pack_window(start, end)).pack()

    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    assert unpack_window(WizCb.unpack(packed).value) == (start, end)


@pytest.mark.parametrize(("start", "end"), WINDOW_PRESETS, ids=lambda part: str(part))
def test_a_pressed_window_and_a_typed_one_mean_the_same_pair(start, end):
    """One window, two ways in: the atom and the keyboard must agree."""
    pressed = unpack_window(pack_window(start, end))
    typed = parse_user_window(f"{start}-{end}")

    assert (parse_hhmm(pressed[0]), parse_hhmm(pressed[1])) == typed


def test_the_window_atom_is_the_length_the_contract_names():
    """The handler measures the atom by this constant before unpacking it."""
    for start, end in WINDOW_PRESETS:
        assert len(pack_window(start, end)) == WINDOW_ATOM_LENGTH


def test_every_missing_day_atom_names_a_rule_the_schedule_accepts():
    """A button that maps onto nothing would write junk into JSONB."""
    for atom, rule in MISSING_DAY_ATOMS.items():
        assert atom in _values(missing_day_kb("ru"), "miss")
        parse_schedule({"kind": "monthly", "times": ["10:00"], "days": [1], "on_missing_day": rule})

    assert set(_values(missing_day_kb("ru"), "miss")) == set(MISSING_DAY_ATOMS)


def test_the_pickers_offer_every_day_the_schedule_allows():
    """A day with no button is a day the user can never choose."""
    assert set(_values(weekly_days_kb([], "ru"), "wday")) == {
        *(str(day) for day in ALL_WEEKDAYS),
        "ok",
    }
    assert set(_values(monthday_kb([], "ru"), "mday")) == {
        *(str(day) for day in ALL_MONTH_DAYS),
        "ok",
    }


def test_every_interval_preset_is_a_step_the_schedule_accepts():
    for minutes in INTERVAL_PRESETS:
        assert INTERVAL_MIN_MINUTES <= minutes <= INTERVAL_MAX_MINUTES


@pytest.mark.parametrize(
    ("keyboard", "step", "chosen"),
    [
        (weekly_days_kb, "wday", 3),
        (monthday_kb, "mday", 15),
    ],
    ids=["weekdays", "month_days"],
)
def test_a_day_picker_marks_what_is_chosen_without_changing_its_atoms(keyboard, step, chosen):
    """A toggle changes the label, never the callback it sends."""
    empty = keyboard([], "ru")
    marked = keyboard([chosen], "ru")

    assert _callbacks(empty) == _callbacks(marked)
    assert any(label.startswith(SELECTED_MARK) for label in _labels(marked))
    assert not any(label.startswith(SELECTED_MARK) for label in _labels(empty))
    assert step in {WizCb.unpack(data).step for data in _callbacks(marked) if _is_wiz(data)}


def test_time_presets_are_unique():
    assert len(set(DAILY_TIME_PRESETS)) == len(DAILY_TIME_PRESETS)


def test_the_kind_step_offers_exactly_the_kinds_the_wizard_builds():
    """A button for a kind the wizard cannot build is a dead end."""
    assert set(_values(schedule_kind_kb("ru"), "kind")) == {
        kind.value for kind in WIZARD_SCHEDULE_KINDS
    }
    assert set(WIZARD_SCHEDULE_KINDS).issubset(set(ScheduleKind))


def test_every_wizard_screen_can_be_cancelled_by_the_shared_atom():
    """Cancelling is one atom across the product, not one per screen."""
    cancel = WizCb(step="confirm", value="no").pack()

    for keyboard in KEYBOARDS.values():
        assert cancel in _callbacks(keyboard)


def test_the_daily_picker_marks_what_is_already_chosen():
    """The list lives in FSM data, so the keyboard is the only place it shows."""
    chosen = DAILY_TIME_PRESETS[0]
    labels = _labels(daily_times_kb([chosen], "ru"))

    assert f"{SELECTED_MARK}{chosen}" in labels
    assert chosen not in labels


def test_the_daily_picker_keeps_the_same_atoms_whatever_is_chosen():
    """A toggle changes the label, never the callback it sends."""
    assert _callbacks(daily_times_kb([], "ru")) == _callbacks(
        daily_times_kb(DAILY_TIME_PRESETS, "ru")
    )


def test_the_date_atom_needs_no_packing():
    """ISO dates carry no colon, so they travel whole (tech.md 18.1)."""
    day = date(2026, 9, 1)
    packed = WizCb(step="date", value=format_local_date(day)).pack()

    assert parse_local_date(WizCb.unpack(packed).value) == day


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "once", "at": "2026-09-01T07:30"},
        {"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1},
        {"kind": "weekly", "times": ["07:30"], "weekdays": [1, 3, 5]},
        {"kind": "monthly", "times": ["10:00"], "days": [1, 15], "on_missing_day": "last_day"},
        {"kind": "monthly", "times": ["10:00"], "days": [31], "on_missing_day": "skip"},
        {
            "kind": "interval",
            "every_minutes": 120,
            "window_start": "09:00",
            "window_end": "21:00",
        },
    ],
    ids=["once", "daily", "weekly", "monthly_last_day", "monthly_skip", "interval"],
)
def test_the_wizard_payload_validates_against_the_schedule_contract(payload):
    """What the wizard writes into JSONB is what tech.md 5 accepts."""
    assert dump_schedule(parse_schedule(payload)) == payload


def test_the_named_limit_is_the_limit_the_model_enforces():
    """The wizard quotes this number at the user; the model must mean it."""
    times = [f"{hour:02d}:00" for hour in range(TIMES_MAX_LENGTH + 1)]

    parse_schedule({"kind": "daily", "times": times[:TIMES_MAX_LENGTH]})
    with pytest.raises(ValueError):
        parse_schedule({"kind": "daily", "times": times})


def test_the_daily_picker_never_offers_more_than_the_schedule_holds():
    assert len(DAILY_TIME_PRESETS) <= TIMES_MAX_LENGTH


@pytest.mark.parametrize("raw", ["2026-9-1", "01.09.2026", "20260901", "2026-09-01T07:30", ""])
def test_a_date_outside_the_one_format_is_refused(raw):
    with pytest.raises(ValueError):
        parse_local_date(raw)


def test_a_date_never_smuggles_a_time_along():
    """`datetime` is a `date`; accepting one would drop the time silently."""
    with pytest.raises(ValueError):
        parse_local_date(datetime(2026, 9, 1, 7, 30))


def _callbacks(keyboard) -> set[str]:
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }


def _labels(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _is_wiz(data: str) -> bool:
    try:
        WizCb.unpack(data)
    except (TypeError, ValueError):
        return False
    return True


def _values(keyboard, step: str) -> list[str]:
    values = []
    for data in _callbacks(keyboard):
        try:
            unpacked = WizCb.unpack(data)
        except (TypeError, ValueError):
            continue
        if unpacked.step == step:
            values.append(unpacked.value)
    return values
