from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DatabaseSettings(BaseSettings):
    """Only what migrations need: the `migrate` service gets POSTGRES_* and nothing else."""

    model_config = SettingsConfigDict(extra="ignore")

    postgres_host: str
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: str
    postgres_db: str

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


class Settings(DatabaseSettings):
    # Public prefix for product images, e.g. http://localhost:8080/media
    media_base_url: str

    minio_endpoint_url: str
    minio_root_user: str
    minio_root_password: SecretStr
    minio_bucket: str

    # Shared secret the bot sends in X-Internal-Token.
    internal_token: SecretStr = Field(min_length=16)
    max_image_bytes: int = Field(default=10 * 1024 * 1024, gt=0)


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
