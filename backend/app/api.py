from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Product
from app.schemas import ProductOut

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health")
async def health(session: SessionDep) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}


@router.get("/products")
async def list_products(
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProductOut]:
    rows = await session.scalars(
        select(Product)
        .order_by(Product.created_at.desc(), Product.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [ProductOut.from_model(p, settings.media_base_url) for p in rows]
