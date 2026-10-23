from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import router
from app.config import get_settings
from app.storage import create_s3_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with AsyncExitStack() as stack:
        # Per-process connection pool; no schema changes here (migrations run in `migrate`).
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        stack.push_async_callback(engine.dispose)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        # The bucket is created by `minio-init`, not here.
        app.state.s3 = await create_s3_client(settings, stack)
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="Test Catalog API", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
