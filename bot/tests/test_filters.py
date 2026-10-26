from datetime import UTC, datetime

import pytest
from aiogram.types import Chat, Message, User

from app.config import Settings
from app.filters import IsAdmin
from tests.conftest import ADMIN_ID, USER_ID


def message(user_id: int | None) -> Message:
    user = User(id=user_id, is_bot=False, first_name="U") if user_id is not None else None
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id or -1, type="private"),
        from_user=user,
    )


@pytest.mark.parametrize(
    ("user_id", "expected"), [(ADMIN_ID, True), (USER_ID, False), (None, False)]
)
async def test_is_admin(settings: Settings, user_id: int | None, expected: bool) -> None:
    assert await IsAdmin()(message(user_id), settings=settings) is expected


def test_admin_ids_parsed_from_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_IDS", " 1, 2,,3 ")
    s = Settings(
        bot_token="42:TEST",
        webhook_secret="x",
        webapp_url="https://catalog.test/",
        internal_token="t" * 16,
    )
    assert s.admin_ids == frozenset({1, 2, 3})
