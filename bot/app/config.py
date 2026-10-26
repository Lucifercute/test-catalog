import re
from functools import lru_cache
from typing import Annotated

from pydantic import AnyHttpUrl, Field, HttpUrl, SecretStr, UrlConstraints, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Allowed by Telegram for setWebhook's secret_token.
WEBHOOK_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")
# Telegram opens Mini Apps and delivers webhooks over HTTPS only.
HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]


class TelegramSettings(BaseSettings):
    """Shared by the bot replicas and the one-shot `bot-setup`."""

    model_config = SettingsConfigDict(extra="ignore")

    bot_token: SecretStr
    # Sent by Telegram in X-Telegram-Bot-Api-Secret-Token; the same on every replica.
    webhook_secret: SecretStr
    webapp_url: HttpsUrl
    # Comma-separated Telegram user ids: ADMIN_IDS=1,2,3
    admin_ids: Annotated[frozenset[int], NoDecode] = frozenset()

    @field_validator("webhook_secret")
    @classmethod
    def check_webhook_secret(cls, value: SecretStr) -> SecretStr:
        if not WEBHOOK_SECRET_RE.fullmatch(value.get_secret_value()):
            raise ValueError("must be 1-256 chars of A-Z, a-z, 0-9, _ and -")
        return value

    @field_validator("admin_ids", mode="before")
    @classmethod
    def split_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return {part.strip() for part in value.split(",") if part.strip()}
        return value


class SetupSettings(TelegramSettings):
    # Public HTTPS origin Telegram posts updates to: PUBLIC_BASE_URL + WEBHOOK_PATH.
    public_base_url: HttpsUrl


class Settings(TelegramSettings):
    # Through Caddy, so requests are balanced across backend replicas.
    backend_url: AnyHttpUrl = AnyHttpUrl("http://caddy/api")
    # Shared secret sent to the backend in X-Internal-Token.
    internal_token: SecretStr = Field(min_length=16)
    # Well below aiogram's 55 s webhook budget.
    backend_timeout: float = Field(default=15.0, gt=0)


@lru_cache
def get_setup_settings() -> SetupSettings:
    return SetupSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
