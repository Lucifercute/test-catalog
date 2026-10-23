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

from alembic import command
from app.config import get_settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent
MEDIA_BASE_URL = "http://media.test/media/"


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
        get_settings.cache_clear()
        # Exercise the real migration instead of metadata.create_all().
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        yield
    get_settings.cache_clear()


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    app = create_app()
    async with LifespanManager(app):
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
