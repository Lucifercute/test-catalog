import email
import email.policy
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, SendMessage, TelegramMethod
from aiogram.types import Chat, File, Message

from app.config import Settings

ADMIN_ID = 100
USER_ID = 200
WEBHOOK_SECRET = "test-webhook-secret"
INTERNAL_TOKEN = "test-internal-token-0123456789"
BACKEND_URL = "http://backend.test/api"
PHOTO_BYTES = b"\xff\xd8\xff\xe0" + b"photo" * 8


class FakeSession(BaseSession):
    """Records Bot API calls instead of sending them; serves PHOTO_BYTES for downloads."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.downloads: list[str] = []

    async def close(self) -> None:
        pass

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 (BaseSession signature)
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="photos/big.jpg")
        if isinstance(method, SendMessage):
            return Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 (BaseSession signature)
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        self.downloads.append(url)
        yield PHOTO_BYTES

    def sent_texts(self) -> list[str]:
        return [m.text for m in self.requests if isinstance(m, SendMessage)]


class FakeBackend:
    """httpx.MockTransport handler: records requests, replies with `response` (or raises it)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response: httpx.Response | Exception = httpx.Response(201)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def multipart_fields(request: httpx.Request) -> dict[str, bytes]:
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n"
    msg = email.message_from_bytes(raw + request.read(), policy=email.policy.HTTP)
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
        for part in msg.iter_parts()
    }


def message_update(user_id: int, *, update_id: int = 1, message_id: int = 7, **fields: Any) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "U"},
            **fields,
        },
    }


PHOTO_SIZES = [
    {"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90},
    {"file_id": "big", "file_unique_id": "b", "width": 1280, "height": 1280},
]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="42:TEST",
        webhook_secret=WEBHOOK_SECRET,
        webapp_url="https://catalog.test/",
        admin_ids=f"{ADMIN_ID}",
        internal_token=INTERNAL_TOKEN,
        backend_url=BACKEND_URL,
    )


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(session: FakeSession) -> Bot:
    return Bot("42:TEST", session=session)


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()
