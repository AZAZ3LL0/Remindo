"""The creation wizard must survive a restart of the bot process."""

from aiogram.fsm.storage.base import StorageKey

from app.bot.fsm.reminder_wizard import ReminderWizard
from app.bot.fsm.storage import SQLAlchemyStorage, storage_key_to_text

KEY = StorageKey(bot_id=42, chat_id=100, user_id=100)


async def test_state_and_data_outlive_the_process(session_factory):
    before_restart = SQLAlchemyStorage(session_factory)
    await before_restart.set_state(KEY, ReminderWizard.title)
    await before_restart.update_data(KEY, {"category_id": 7})

    # A new storage instance is what a restarted process gets.
    after_restart = SQLAlchemyStorage(session_factory)

    assert await after_restart.get_state(KEY) == "ReminderWizard:title"
    assert await after_restart.get_data(KEY) == {"category_id": 7}


async def test_clearing_the_state_keeps_the_row_usable(session_factory):
    storage = SQLAlchemyStorage(session_factory)
    await storage.set_state(KEY, ReminderWizard.title)

    await storage.set_state(KEY, None)
    await storage.set_data(KEY, {})

    assert await storage.get_state(KEY) is None
    assert await storage.get_data(KEY) == {}


async def test_unknown_key_reads_as_empty(session_factory):
    storage = SQLAlchemyStorage(session_factory)
    other = StorageKey(bot_id=42, chat_id=1, user_id=2)

    assert await storage.get_state(other) is None
    assert await storage.get_data(other) == {}


def test_storage_key_is_stable_and_scoped():
    """Key layout is part of the storage contract: one row per conversation."""
    assert storage_key_to_text(KEY) == "42:100:100:0::default"
    assert storage_key_to_text(StorageKey(bot_id=42, chat_id=100, user_id=101)) != (
        storage_key_to_text(KEY)
    )
