from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SetChatMenuButton, SetMyCommands, SetWebhook, TelegramMethod
from aiogram.types import BotCommandScopeChat

from app.config import SetupSettings
from app.setup import setup_bot
from tests.conftest import ADMIN_ID, WEBHOOK_SECRET, FakeSession

OTHER_ADMIN_ID = 300


class NoChatSession(FakeSession):
    """Telegram refuses chat-scoped commands for an admin who never wrote to the bot."""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 (BaseSession signature)
    ) -> Any:
        scope = getattr(method, "scope", None)
        if isinstance(scope, BotCommandScopeChat) and scope.chat_id == OTHER_ADMIN_ID:
            self.requests.append(method)
            raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        return await super().make_request(bot, method, timeout)


async def test_setup_bot() -> None:
    session = NoChatSession()
    settings = SetupSettings(
        bot_token="42:TEST",
        webhook_secret=WEBHOOK_SECRET,
        webapp_url="https://catalog.test/app",
        admin_ids=f"{OTHER_ADMIN_ID},{ADMIN_ID}",
        public_base_url="https://bot.example.com/",
    )

    await setup_bot(Bot("42:TEST", session=session), settings)

    [webhook] = [m for m in session.requests if isinstance(m, SetWebhook)]
    assert webhook.url == "https://bot.example.com/tg/webhook"
    assert webhook.secret_token == WEBHOOK_SECRET
    assert set(webhook.allowed_updates) == {"message", "callback_query"}
    assert webhook.drop_pending_updates is False

    commands = {
        getattr(m.scope, "chat_id", None): [c.command for c in m.commands]
        for m in session.requests
        if isinstance(m, SetMyCommands)
    }
    # One unreachable admin doesn't stop the rest of the setup.
    assert commands == {
        None: ["start"],
        ADMIN_ID: ["start", "new"],
        OTHER_ADMIN_ID: ["start", "new"],
    }

    [menu] = [m for m in session.requests if isinstance(m, SetChatMenuButton)]
    assert menu.menu_button.web_app.url == "https://catalog.test/app"
