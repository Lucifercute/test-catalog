from itertools import count

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DatabaseSettings
from app.models import Product
from tests.conftest import BUCKET, INTERNAL_TOKEN, MAX_IMAGE_BYTES

# Minimal byte strings: only the magic header matters for the type check.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

# MinIO is shared across tests and not cleaned; unique chat ids keep tests independent.
_chat_ids = count(1000)


@pytest.fixture
def chat_id() -> int:
    return next(_chat_ids)


async def post_product(
    client: AsyncClient,
    chat_id: int,
    *,
    message_id: int = 1,
    title: str = "Mug",
    image: bytes = PNG,
    content_type: str = "image/png",
    token: str | None = INTERNAL_TOKEN,
) -> Response:
    headers = {"X-Internal-Token": token} if token is not None else {}
    return await client.post(
        "/products",
        data={"title": title, "chat_id": str(chat_id), "message_id": str(message_id)},
        files={"image": ("photo", image, content_type)},
        headers=headers,
    )


async def count_rows(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Product))


async def list_keys(app: FastAPI, chat_id: int) -> list[str]:
    resp = await app.state.s3.list_objects_v2(Bucket=BUCKET, Prefix=f"products/{chat_id}/")
    return [obj["Key"] for obj in resp.get("Contents", [])]


async def test_create(
    client: AsyncClient, session: AsyncSession, app: FastAPI, chat_id: int
) -> None:
    response = await post_product(client, chat_id, title="  Mug  ")

    assert response.status_code == 201
    body = response.json()
    key = f"products/{chat_id}/1.png"
    assert body["title"] == "Mug"
    assert body["image_url"] == f"/media/{key}"

    product = await session.scalar(select(Product))
    assert product is not None
    assert (product.image_key, product.chat_id, product.message_id) == (key, chat_id, 1)

    obj = await app.state.s3.get_object(Bucket=BUCKET, Key=key)
    async with obj["Body"] as stream:
        assert await stream.read() == PNG
    assert obj["ContentType"] == "image/png"

    listed = (await client.get("/products")).json()
    assert [p["id"] for p in listed] == [body["id"]]


async def test_jpeg_gets_jpg_extension(client: AsyncClient, app: FastAPI, chat_id: int) -> None:
    response = await post_product(client, chat_id, image=JPEG, content_type="image/jpeg")

    assert response.status_code == 201
    assert await list_keys(app, chat_id) == [f"products/{chat_id}/1.jpg"]


async def test_duplicate_returns_existing(
    client: AsyncClient, session: AsyncSession, chat_id: int
) -> None:
    first = await post_product(client, chat_id, title="First")
    second = await post_product(client, chat_id, title="Retry")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert await count_rows(session) == 1


@pytest.mark.parametrize("token", [None, "wrong-token", INTERNAL_TOKEN + "x"])
async def test_rejects_bad_token(
    client: AsyncClient, session: AsyncSession, app: FastAPI, chat_id: int, token: str | None
) -> None:
    response = await post_product(client, chat_id, token=token)

    assert response.status_code == 401
    assert await count_rows(session) == 0
    assert await list_keys(app, chat_id) == []


async def test_bad_token_wins_over_invalid_form(client: AsyncClient, chat_id: int) -> None:
    response = await post_product(client, chat_id, title="", token="wrong-token")

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("image", "content_type"),
    [
        (b"hello", "text/plain"),
        (b"GIF89a" + b"\x00" * 16, "image/gif"),
        (b"not really a png", "image/png"),  # header lies about the content
        (JPEG, "image/png"),  # real image, mismatched header
    ],
)
async def test_rejects_wrong_type(
    client: AsyncClient,
    session: AsyncSession,
    app: FastAPI,
    chat_id: int,
    image: bytes,
    content_type: str,
) -> None:
    response = await post_product(client, chat_id, image=image, content_type=content_type)

    assert response.status_code == 415
    assert await count_rows(session) == 0
    assert await list_keys(app, chat_id) == []


async def test_rejects_too_large(
    client: AsyncClient, session: AsyncSession, app: FastAPI, chat_id: int
) -> None:
    big = PNG + b"\x00" * MAX_IMAGE_BYTES

    response = await post_product(client, chat_id, image=big)

    assert response.status_code == 413
    assert await count_rows(session) == 0
    assert await list_keys(app, chat_id) == []


async def test_accepts_exact_size_limit(client: AsyncClient, chat_id: int) -> None:
    exact = PNG + b"\x00" * (MAX_IMAGE_BYTES - len(PNG))

    response = await post_product(client, chat_id, image=exact)

    assert response.status_code == 201


@pytest.mark.parametrize("title", ["", "   ", "x" * 256])
async def test_rejects_bad_title(
    client: AsyncClient, session: AsyncSession, chat_id: int, title: str
) -> None:
    response = await post_product(client, chat_id, title=title)

    assert response.status_code == 422
    assert await count_rows(session) == 0


async def test_accepts_max_title(client: AsyncClient, chat_id: int) -> None:
    response = await post_product(client, chat_id, title="x" * 255)

    assert response.status_code == 201


def test_database_settings_need_only_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    # The `migrate` service gets POSTGRES_* only: no app secrets must be required.
    for name in [
        "MEDIA_BASE_URL",
        "INTERNAL_TOKEN",
        "MAX_IMAGE_BYTES",
        "MINIO_ENDPOINT_URL",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_BUCKET",
    ]:
        monkeypatch.delenv(name, raising=False)

    assert DatabaseSettings().database_url.drivername == "postgresql+asyncpg"
