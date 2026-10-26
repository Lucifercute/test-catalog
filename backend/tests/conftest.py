import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HttpWaitStrategy

from alembic import command
from app.config import get_database_settings, get_settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Relative, as in .env.example; the trailing "/" checks there is no double slash.
MEDIA_BASE_URL = "/media/"
# Same image as in compose.yaml.
MINIO_IMAGE = "pgsty/minio:RELEASE.2026-08-04T00-00-00Z"
MINIO_USER = "minioadmin"
MINIO_PASSWORD = "minioadmin-secret"
BUCKET = "test-images"
INTERNAL_TOKEN = "test-internal-token-0123456789"
MAX_IMAGE_BYTES = 1024


def clear_settings_cache() -> None:
    get_settings.cache_clear()
    get_database_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def minio() -> Iterator[None]:
    container = (
        DockerContainer(MINIO_IMAGE)
        .with_env("MINIO_ROOT_USER", MINIO_USER)
        .with_env("MINIO_ROOT_PASSWORD", MINIO_PASSWORD)
        .with_command("server /data")
        .with_exposed_ports(9000)
        .waiting_for(HttpWaitStrategy(9000, "/minio/health/live"))
    )
    with container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(9000)
        os.environ.update(
            MINIO_ENDPOINT_URL=f"http://{host}:{port}",
            MINIO_ROOT_USER=MINIO_USER,
            MINIO_ROOT_PASSWORD=MINIO_PASSWORD,
            MINIO_BUCKET=BUCKET,
            INTERNAL_TOKEN=INTERNAL_TOKEN,
            MAX_IMAGE_BYTES=str(MAX_IMAGE_BYTES),
        )
        clear_settings_cache()
        yield
    clear_settings_cache()


@pytest.fixture(scope="session", autouse=True)
def postgres() -> Iterator[None]:
    with PostgresContainer("postgres:18.6-alpine", driver=None) as pg:
        os.environ.update(
            POSTGRES_HOST=pg.get_container_host_ip(),
            POSTGRES_PORT=str(pg.get_exposed_port(5432)),
            POSTGRES_USER=pg.username,
            POSTGRES_PASSWORD=pg.password,
            POSTGRES_DB=pg.dbname,
            MEDIA_BASE_URL=MEDIA_BASE_URL,
        )
        clear_settings_cache()
        # Exercise the real migration instead of metadata.create_all().
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        yield
    clear_settings_cache()


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    app = create_app()
    async with LifespanManager(app):
        # In compose the bucket comes from `minio-init`; here the test creates it.
        s3 = app.state.s3
        try:
            await s3.create_bucket(Bucket=BUCKET)
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass
        yield app


@pytest.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.sessionmaker() as session:
        await session.execute(text("TRUNCATE products RESTART IDENTITY"))
        await session.commit()
        yield session


@pytest.fixture
async def client(app: FastAPI, session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
