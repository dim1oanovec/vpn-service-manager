from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Вся конфигурация приложения. Секреты только из окружения / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- Telegram ----------
    bot_token: str
    admin_ids: list[int] = Field(default_factory=list)
    admin_chat_id: int | None = None
    required_channel_id: int | None = None
    required_channel_url: str | None = None
    brand_name: str = "MyVPN"
    support_username: str | None = None
    timezone: str = "Europe/Moscow"

    # ---------- Инфраструктура ----------
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    redis_url: str | None = None
    secret_key: str

    # ---------- 3x-ui сид первого сервера ----------
    xui_base_url: str = ""
    xui_username: str = ""
    xui_password: str = ""
    xui_inbound_id: int = 1
    xui_sub_url: str | None = None
    server_host: str = ""
    server_code: str = "fr-1"
    server_country: str = "Франция"
    server_flag: str = "🇫🇷"
    server_max_clients: int = 300

    # ---------- Платежи ----------
    yookassa_shop_id: str | None = None
    yookassa_secret_key: str | None = None
    stars_enabled: bool = True
    manual_pay_enabled: bool = True
    manual_pay_details: str = ""

    # ---------- Логика ----------
    trial_enabled: bool = True
    trial_days: int = 3
    trial_min_account_age_days: int = 7
    referral_percent: int = 20
    delete_expired_after_days: int = 14
    reissue_cooldown_hours: int = 24

    # ---------- Web ----------
    webhook_enabled: bool = False
    webhook_base_url: str | None = None
    webhook_secret: str | None = None
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(chunk) for chunk in value.replace(";", ",").split(",") if chunk.strip()]
        return value

    @field_validator("xui_base_url", "xui_sub_url", mode="before")
    @classmethod
    def _strip_slash(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def yookassa_enabled(self) -> bool:
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)

    def is_admin(self, telegram_id: int | None) -> bool:
        return telegram_id is not None and telegram_id in self.admin_ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
