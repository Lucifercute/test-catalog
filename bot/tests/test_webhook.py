from collections.abc import AsyncIterator

import httpx
import pytest
from aiogram import Bot
from aiohttp.test_utils import TestClient, TestServer

from app.config import Settings
from app.main import WEBHOOK_PATH, create_app
from tests.conftest import (
    ADMIN_ID,
    INTERNAL_TOKEN,
    PHOTO_SIZES,
    WEBHOOK_SECRET,
    FakeBackend,
    FakeSession,
    message_update,
)

SECRET_HEADER = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}
PHOTO_UPDATE = message_update(ADMIN_ID, photo=PHOTO_SIZES, caption="Mug")


@pytest.fixture
async def client(
    settings: Settings, bot: Bot, fake_backend: FakeBackend
) -> AsyncIterator[TestClient]:
    app = create_app(settings, bot=bot, backend_transport=fake_backend.transport)
    async with TestClient(TestServer(app)) as client:
        yield client


async def test_health(client: TestClient) -> None:
    response = await client.get("/health")
    assert response.status == 200
    assert await response.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"}])
async def test_bad_secret(
    client: TestClient, fake_backend: FakeBackend, headers: dict[str, str]
) -> None:
    response = await client.post(WEBHOOK_PATH, json=PHOTO_UPDATE, headers=headers)

    assert response.status == 401
    assert fake_backend.requests == []


async def test_update_processed_before_ack(
    client: TestClient, session: FakeSession, fake_backend: FakeBackend
) -> None:
    response = await client.post(WEBHOOK_PATH, json=PHOTO_UPDATE, headers=SECRET_HEADER)

    assert response.status == 200
    # handle_in_background=False: by the time Telegram gets 200 the product is created.
    [request] = fake_backend.requests
    assert request.headers["X-Internal-Token"] == INTERNAL_TOKEN
    assert session.sent_texts() == ["Товар «Mug» добавлен."]


async def test_backend_down_makes_telegram_retry(
    client: TestClient, fake_backend: FakeBackend
) -> None:
    fake_backend.response = httpx.ConnectError("refused")
    response = await client.post(WEBHOOK_PATH, json=PHOTO_UPDATE, headers=SECRET_HEADER)
    # Non-2xx: Telegram keeps the update and redelivers it.
    assert response.status == 500

    fake_backend.response = httpx.Response(201)
    response = await client.post(WEBHOOK_PATH, json=PHOTO_UPDATE, headers=SECRET_HEADER)
    assert response.status == 200
    assert len(fake_backend.requests) == 2
