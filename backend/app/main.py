from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Per-process connection pool; no schema changes here (migrations run in `migrate`).
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Test Catalog API", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
