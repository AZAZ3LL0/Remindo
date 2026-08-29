"""States of onboarding and of the settings screens."""

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """First contact. Held until the user has a timezone."""

    timezone = State()


class SettingsForm(StatesGroup):
    """Settings input that spans more than one update.

    Quiet hours ask two questions, so the chosen start waits in FSM data until
    the end arrives. Packing both into one callback value is forbidden by the
    callback contract (tech.md 6).
    """

    timezone = State()
    quiet_start = State()
    quiet_end = State()
