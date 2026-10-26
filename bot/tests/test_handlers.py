from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import AnswerCallbackQuery, GetFile, SendMessage

from app.backend import BackendClient, BackendUnavailable
from app.config import Settings
from app.handlers import CATALOG_TEXT, INSTRUCTION, NEED_CAPTION, NEW_PRODUCT
from app.main import build_dispatcher
from tests.conftest import (
    ADMIN_ID,
    BACKEND_URL,
    INTERNAL_TOKEN,
    PHOTO_BYTES,
    PHOTO_SIZES,
    USER_ID,
    FakeBackend,
    FakeSession,
    message_update,
    multipart_fields,
)


@pytest.fixture
async def backend(fake_backend: FakeBackend) -> AsyncIterator[BackendClient]:
    async with httpx.AsyncClient(base_url=BACKEND_URL, transport=fake_backend.transport) as http:
        yield BackendClient(http, INTERNAL_TOKEN)


@pytest.fixture
def feed(bot: Bot, settings: Settings, backend: BackendClient):
    dispatcher: Dispatcher = build_dispatcher()

    async def feed(update: dict[str, Any]) -> None:
        await dispatcher.feed_raw_update(bot, update, settings=settings, backend=backend)

    return feed


def keyboard_buttons(session: FakeSession) -> list[str]:
    [msg] = [m for m in session.requests if isinstance(m, SendMessage)]
    return [b.text for row in msg.reply_markup.inline_keyboard for b in row]


async def test_start_user_gets_webapp_button(feed, session: FakeSession) -> None:
    await feed(message_update(USER_ID, text="/start"))

    [msg] = [m for m in session.requests if isinstance(m, SendMessage)]
    assert msg.text == CATALOG_TEXT
    [[button]] = msg.reply_markup.inline_keyboard
    assert button.web_app.url == "https://catalog.test/"


async def test_start_admin_also_gets_create_button(feed, session: FakeSession) -> None:
    await feed(message_update(ADMIN_ID, text="/start"))
    assert keyboard_buttons(session) == ["Открыть каталог", "Создать товар"]


async def test_any_text_gets_catalog(feed, session: FakeSession) -> None:
    await feed(message_update(USER_ID, text="hello"))
    assert session.sent_texts() == [CATALOG_TEXT]


async def test_new_command(feed, session: FakeSession) -> None:
    await feed(message_update(ADMIN_ID, text="/new"))
    assert session.sent_texts() == [INSTRUCTION]


async def test_new_command_not_admin(feed, session: FakeSession) -> None:
    await feed(message_update(USER_ID, text="/new"))
    assert session.sent_texts() == [CATALOG_TEXT]


@pytest.mark.parametrize(("user_id", "allowed"), [(ADMIN_ID, True), (USER_ID, False)])
async def test_create_button(feed, session: FakeSession, user_id: int, allowed: bool) -> None:
    await feed(
        {
            "update_id": 1,
            "callback_query": {
                "id": "cb",
                "chat_instance": "ci",
                "from": {"id": user_id, "is_bot": False, "first_name": "U"},
                "data": NEW_PRODUCT,
            },
        }
    )
    [answer] = [m for m in session.requests if isinstance(m, AnswerCallbackQuery)]
    assert answer.show_alert is (None if allowed else True)
    assert session.sent_texts() == ([INSTRUCTION] if allowed else [])


async def test_photo_from_user_is_ignored(
    feed, session: FakeSession, fake_backend: FakeBackend
) -> None:
    await feed(message_update(USER_ID, photo=PHOTO_SIZES, caption="Mug"))

    assert fake_backend.requests == []
    assert session.sent_texts() == [CATALOG_TEXT]


async def test_photo_without_caption(feed, session: FakeSession, fake_backend: FakeBackend) -> None:
    await feed(message_update(ADMIN_ID, photo=PHOTO_SIZES, caption="   "))

    assert fake_backend.requests == []
    assert session.sent_texts() == [NEED_CAPTION]


async def test_album_photo_without_caption_is_silent(feed, session: FakeSession) -> None:
    await feed(message_update(ADMIN_ID, photo=PHOTO_SIZES, media_group_id="g"))
    assert session.sent_texts() == []


async def test_photo_with_caption_creates_product(
    feed, session: FakeSession, fake_backend: FakeBackend
) -> None:
    await feed(message_update(ADMIN_ID, message_id=42, photo=PHOTO_SIZES, caption=" Mug "))

    # The largest size is downloaded.
    assert [m.file_id for m in session.requests if isinstance(m, GetFile)] == ["big"]
    [request] = fake_backend.requests
    assert multipart_fields(request) == {
        "title": b"Mug",
        "chat_id": str(ADMIN_ID).encode(),
        "message_id": b"42",
        "image": PHOTO_BYTES,
    }
    assert session.sent_texts() == ["Товар «Mug» добавлен."]


async def test_photo_already_added(feed, session: FakeSession, fake_backend: FakeBackend) -> None:
    fake_backend.response = httpx.Response(200, json={})
    await feed(message_update(ADMIN_ID, photo=PHOTO_SIZES, caption="Mug"))
    assert session.sent_texts() == ["Товар «Mug» уже был добавлен."]


async def test_photo_rejected(feed, session: FakeSession, fake_backend: FakeBackend) -> None:
    fake_backend.response = httpx.Response(413)
    await feed(message_update(ADMIN_ID, photo=PHOTO_SIZES, caption="Mug"))
    assert session.sent_texts() == ["Товар не добавлен: Фото слишком большое."]


async def test_backend_auth_error_is_reported(
    feed, session: FakeSession, fake_backend: FakeBackend
) -> None:
    fake_backend.response = httpx.Response(401)
    await feed(message_update(ADMIN_ID, photo=PHOTO_SIZES, caption="Mug"))
    assert session.sent_texts() == ["Внутренняя ошибка, товар не добавлен."]


async def test_backend_unavailable_propagates(
    feed, session: FakeSession, fake_backend: FakeBackend
) -> None:
    fake_backend.response = httpx.ConnectError("refused")
    with pytest.raises(BackendUnavailable):
        await feed(message_update(ADMIN_ID, photo=PHOTO_SIZES, caption="Mug"))
    # No reply: Telegram will redeliver, and each retry would spam the admin.
    assert session.sent_texts() == []


@pytest.mark.parametrize(
    ("error", "retried"),
    [(TelegramForbiddenError, False), (TelegramNetworkError, True)],
)
async def test_telegram_errors(
    feed, session: FakeSession, error: type[Exception], retried: bool
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise error(method=SendMessage(chat_id=USER_ID, text="x"), message="boom")

    session.make_request = fail
    update = message_update(USER_ID, text="/start")
    if retried:
        # Transient: propagates -> 500 -> Telegram redelivers.
        with pytest.raises(error):
            await feed(update)
    else:
        # Permanent (e.g. user blocked the bot): acked, no endless redelivery.
        await feed(update)
