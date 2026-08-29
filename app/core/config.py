"""The only module allowed to read the process environment."""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    bot_token: str = "000000:fake-token-for-local-dev"
    bot_mode: Literal["polling", "webhook"] = "polling"
    webhook_base_url: str = ""

    database_url: str = "postgresql+asyncpg://app:app@db:5432/reminder"

    default_timezone: str = "Europe/Moscow"
    default_language: Literal["ru", "en"] = "ru"

    planner_horizon_hours: int = Field(default=48, ge=1, le=24 * 30)
    planner_interval_seconds: int = Field(default=60, ge=1)
    dispatch_interval_seconds: int = Field(default=10, ge=1)
    dispatch_batch_size: int = Field(default=100, ge=1)
    delivery_lock_seconds: int = Field(default=60, ge=1)
    occurrence_ttl_minutes: int = Field(default=180, ge=1)

    use_fake_bot: bool = False
    admin_user_ids: str = ""

    @field_validator("default_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @property
    def admin_ids(self) -> frozenset[int]:
        return frozenset(int(part) for part in self.admin_user_ids.split(",") if part.strip())

    @property
    def default_tz(self) -> ZoneInfo:
        return ZoneInfo(self.default_timezone)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
