"""States of the reminder edit screens (tech.md 21.2).

One state per question, the way the wizard does it. The reminder being edited
rides in FSM data, which is what lets the value screens reuse the shared
`WizCb` atoms and the shared category picker: the screens are told apart by the
state, not by a factory of their own.

Changing the schedule has no state here. It re-enters the wizard at
`ReminderWizard.kind` with the reminder id in data, because the questions are
the same ones and a second copy of them would be a second copy to keep in step.
"""

from aiogram.fsm.state import State, StatesGroup


class ReminderEdit(StatesGroup):
    title = State()
    note = State()
    category = State()
    snooze = State()
    repeat = State()
