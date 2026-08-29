"""States of the reminder creation wizard (reference slice: water)."""

from aiogram.fsm.state import State, StatesGroup


class ReminderWizard(StatesGroup):
    category = State()
    title = State()
    every_minutes = State()
    window = State()
    confirm = State()


class Onboarding(StatesGroup):
    timezone = State()
