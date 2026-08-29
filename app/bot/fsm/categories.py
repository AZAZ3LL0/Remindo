"""States of the category screens."""

from aiogram.fsm.state import State, StatesGroup


class CategoryForm(StatesGroup):
    """Category input that spans more than one update.

    Creation asks two questions, so the title waits in FSM data until the
    emoji arrives. Renaming reuses neither, because it edits an existing row
    and therefore carries the category id instead.
    """

    title = State()
    emoji = State()
    rename = State()
