"""SQLAlchemy-backed FSM storage, so a wizard survives a restart of `bot`."""

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FSMState


def storage_key_to_text(key: StorageKey) -> str:
    parts = (
        key.bot_id,
        key.chat_id,
        key.user_id,
        key.thread_id or 0,
        key.business_connection_id or "",
        key.destiny,
    )
    return ":".join(str(part) for part in parts)


class SQLAlchemyStorage(BaseStorage):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self._upsert(key, state=value)

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self._get(key)
        return row.state if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self._upsert(key, data=dict(data))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await self._get(key)
        return dict(row.data) if row else {}

    async def close(self) -> None:
        return None

    async def _get(self, key: StorageKey) -> FSMState | None:
        async with self._session_factory() as session:
            return await session.get(FSMState, storage_key_to_text(key))

    async def _upsert(self, key: StorageKey, **values: Any) -> None:
        text_key = storage_key_to_text(key)
        async with self._session_factory() as session:
            stmt = pg_insert(FSMState).values(key=text_key, **values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={**values, "updated_at": sa.func.now()},
            )
            await session.execute(stmt)
            await session.commit()
