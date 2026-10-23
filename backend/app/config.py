from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    postgres_host: str
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: str
    postgres_db: str

    # Public prefix for product images, e.g. http://localhost:8080/media
    media_base_url: str

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
