import secrets
from typing import TYPE_CHECKING, Annotated, Any

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import StringConstraints
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Product
from app.schemas import TITLE_MAX_LENGTH, ProductOut
from app.storage import ALLOWED_TYPES, image_key, put_image, sniff_image_type

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client
else:
    # FastAPI inspects annotations at runtime; the stubs are a dev-only dependency.
    S3Client = Any

router = APIRouter()


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
S3Dep = Annotated[S3Client, Depends(get_s3)]


def verify_internal_token(
    settings: SettingsDep,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.internal_token.get_secret_value().encode()
    if x_internal_token is None or not secrets.compare_digest(x_internal_token.encode(), expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


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


async def get_by_message(session: AsyncSession, chat_id: int, message_id: int) -> Product | None:
    return await session.scalar(
        select(Product).where(Product.chat_id == chat_id, Product.message_id == message_id)
    )


@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_internal_token)],
)
async def create_product(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    s3: S3Dep,
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH),
        Form(),
    ],
    chat_id: Annotated[int, Form()],
    message_id: Annotated[int, Form(ge=1)],
    image: Annotated[UploadFile, File()],
) -> ProductOut:
    """Idempotent by (chat_id, message_id): 201 when created, 200 with the existing product."""
    too_large = HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="image too large"
    )
    limit = settings.max_image_bytes
    if image.size is not None and image.size > limit:
        raise too_large
    data = await image.read(limit + 1)
    if len(data) > limit:
        raise too_large

    content_type = image.content_type
    if content_type not in ALLOWED_TYPES or sniff_image_type(data) != content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"image must be one of: {', '.join(ALLOWED_TYPES)}",
        )

    # Fast path for retries: don't re-upload what is already stored.
    existing = await get_by_message(session, chat_id, message_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return ProductOut.from_model(existing, settings.media_base_url)

    key = image_key(chat_id, message_id, ALLOWED_TYPES[content_type])
    try:
        await put_image(s3, settings.minio_bucket, key, data, content_type)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="storage unavailable"
        ) from exc

    product = await session.scalar(
        insert(Product)
        .values(title=title, image_key=key, chat_id=chat_id, message_id=message_id)
        .on_conflict_do_nothing(constraint="uq_products_chat_message")
        .returning(Product)
    )
    await session.commit()
    if product is None:
        # Another replica inserted the same message concurrently.
        product = await get_by_message(session, chat_id, message_id)
        assert product is not None
        response.status_code = status.HTTP_200_OK
    return ProductOut.from_model(product, settings.media_base_url)
