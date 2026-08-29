"""States of the reminder creation wizard (tech.md 15, S3).

The wizard asks category, title and schedule kind, then branches: a `once`
reminder needs a day and a time, a `daily` one a list of times, an `interval`
one a step and a window. The branches meet again at `confirm`, which reads the
finished payload out of FSM data and no longer knows which kind produced it.
"""

from aiogram.fsm.state import State, StatesGroup


class ReminderWizard(StatesGroup):
    category = State()
    title = State()
    kind = State()
    date = State()
    at = State()
    times = State()
    every_minutes = State()
    window = State()
    confirm = State()
