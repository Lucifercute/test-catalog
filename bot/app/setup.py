"""One-shot `bot-setup` (like `migrate`): registers the webhook, commands and menu button.

Idempotent: safe to rerun. The bot replicas never call any of this.
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonWebApp, WebAppInfo

from app.config import SetupSettings, get_setup_settings
from app.main import WEBHOOK_PATH, build_dispatcher

logger = logging.getLogger(__name__)

USER_COMMANDS = [BotCommand(command="start", description="Открыть каталог")]
ADMIN_COMMANDS = [*USER_COMMANDS, BotCommand(command="new", description="Создать товар")]


async def setup_bot(bot: Bot, settings: SetupSettings) -> None:
    url = str(settings.public_base_url).rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(
        url=url,
        secret_token=settings.webhook_secret.get_secret_value(),
        allowed_updates=build_dispatcher().resolve_used_update_types(),
        # Keep updates that arrived while the bot was down.
        drop_pending_updates=False,
    )
    logger.info("webhook set to %s", url)

    await bot.set_my_commands(USER_COMMANDS)
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramBadRequest as exc:
            # E.g. "chat not found" until the admin has written to the bot once.
            logger.warning("admin commands not set for %s: %s", admin_id, exc.message)

    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Каталог", web_app=WebAppInfo(url=str(settings.webapp_url))
        )
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_setup_settings()
    async with Bot(settings.bot_token.get_secret_value()) as bot:
        await setup_bot(bot, settings)


if __name__ == "__main__":
    asyncio.run(main())
