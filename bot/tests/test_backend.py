from collections.abc import AsyncIterator

import httpx
import pytest

from app.backend import (
    BackendClient,
    BackendError,
    BackendUnavailable,
    CreateResult,
    ProductRejected,
)
from tests.conftest import BACKEND_URL, INTERNAL_TOKEN, PHOTO_BYTES, FakeBackend, multipart_fields


@pytest.fixture
async def client(fake_backend: FakeBackend) -> AsyncIterator[BackendClient]:
    async with httpx.AsyncClient(base_url=BACKEND_URL, transport=fake_backend.transport) as http:
        yield BackendClient(http, INTERNAL_TOKEN)


async def create(client: BackendClient) -> CreateResult:
    return await client.create_product(title="Mug", chat_id=-5, message_id=7, image=PHOTO_BYTES)


async def test_sends_multipart_with_token(client: BackendClient, fake_backend: FakeBackend) -> None:
    await create(client)

    [request] = fake_backend.requests
    assert request.method == "POST"
    assert str(request.url) == f"{BACKEND_URL}/products"
    assert request.headers["X-Internal-Token"] == INTERNAL_TOKEN
    assert multipart_fields(request) == {
        "title": b"Mug",
        "chat_id": b"-5",
        "message_id": b"7",
        "image": PHOTO_BYTES,
    }
    assert b'filename="photo.jpg"' in request.content
    assert b"Content-Type: image/jpeg" in request.content


@pytest.mark.parametrize(
    ("status", "expected"), [(201, CreateResult.CREATED), (200, CreateResult.EXISTS)]
)
async def test_success(
    client: BackendClient, fake_backend: FakeBackend, status: int, expected: CreateResult
) -> None:
    fake_backend.response = httpx.Response(status, json={})
    assert await create(client) is expected


@pytest.mark.parametrize("status", [413, 415, 422])
async def test_rejected(client: BackendClient, fake_backend: FakeBackend, status: int) -> None:
    fake_backend.response = httpx.Response(status)
    with pytest.raises(ProductRejected) as exc_info:
        await create(client)
    assert exc_info.value.reason


@pytest.mark.parametrize("status", [400, 401, 404])
async def test_permanent_error(
    client: BackendClient, fake_backend: FakeBackend, status: int
) -> None:
    fake_backend.response = httpx.Response(status)
    with pytest.raises(BackendError):
        await create(client)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(503),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_unavailable(
    client: BackendClient, fake_backend: FakeBackend, response: httpx.Response | Exception
) -> None:
    fake_backend.response = response
    with pytest.raises(BackendUnavailable):
        await create(client)
