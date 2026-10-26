import logging
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart, ExceptionTypeFilter
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.backend import BackendClient, BackendError, CreateResult, ProductRejected
from app.config import Settings
from app.filters import IsAdmin, is_admin

logger = logging.getLogger(__name__)

NEW_PRODUCT = "new_product"
CATALOG_TEXT = "У меня есть товар"
INSTRUCTION = "Пришли фото с подписью-названием одним сообщением."
NEED_CAPTION = "Добавь подпись — это будет название товара. " + INSTRUCTION


def catalog_keyboard(settings: Settings, *, admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Открыть каталог", web_app=WebAppInfo(url=str(settings.webapp_url))
            )
        ]
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="Создать товар", callback_data=NEW_PRODUCT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_catalog(message: Message, settings: Settings) -> None:
    admin = is_admin(message.from_user, settings)
    await message.answer(CATALOG_TEXT, reply_markup=catalog_keyboard(settings, admin=admin))


async def start(message: Message, settings: Settings) -> None:
    await send_catalog(message, settings)


async def new_product_command(message: Message) -> None:
    await message.answer(INSTRUCTION)


async def new_product_button(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    await bot.send_message(callback.from_user.id, INSTRUCTION)


async def new_product_forbidden(callback: CallbackQuery) -> None:
    await callback.answer("Нет доступа", show_alert=True)


async def create_product(message: Message, bot: Bot, backend: BackendClient) -> None:
    """Transient failures (BackendUnavailable, Telegram network errors) propagate on purpose:
    the webhook answers 500 and Telegram redelivers; the backend is idempotent."""
    title = (message.caption or "").strip()
    if not title:
        # Album photos after the first one have no caption: don't answer each of them.
        if message.media_group_id is None:
            await message.answer(NEED_CAPTION)
        return

    assert message.photo is not None
    image = BytesIO()
    # Largest size, in memory only: replicas keep no local files.
    await bot.download(message.photo[-1], destination=image)

    try:
        result = await backend.create_product(
            title=title,
            chat_id=message.chat.id,
            message_id=message.message_id,
            image=image.getvalue(),
        )
    except ProductRejected as exc:
        await message.answer(f"Товар не добавлен: {exc.reason}")
        return
    except BackendError:
        logger.exception(
            "backend refused product chat_id=%s message_id=%s", message.chat.id, message.message_id
        )
        await message.answer("Внутренняя ошибка, товар не добавлен.")
        return

    if result is CreateResult.CREATED:
        await message.answer(f"Товар «{title}» добавлен.")
    else:
        await message.answer(f"Товар «{title}» уже был добавлен.")


async def fallback(message: Message, settings: Settings) -> None:
    await send_catalog(message, settings)


async def telegram_refused(event: ErrorEvent) -> None:
    """Telegram refused a call for good (bot blocked, bad request): a redelivery would fail
    the same way, so ack the update instead of making Telegram retry it.
    Everything else (backend down, Telegram network/5xx/flood) stays unhandled -> 500 -> retry."""
    logger.warning("update %s dropped: %r", event.update.update_id, event.exception)


def build_router() -> Router:
    """A fresh router per dispatcher (a Router can be attached only once).

    No FSM: every scenario fits in one message, so any replica can handle any update.
    """
    router = Router()
    router.message.register(start, CommandStart())
    router.message.register(new_product_command, Command("new"), IsAdmin())
    router.callback_query.register(new_product_button, F.data == NEW_PRODUCT, IsAdmin())
    router.callback_query.register(new_product_forbidden, F.data == NEW_PRODUCT)
    router.message.register(create_product, F.photo, IsAdmin())
    router.message.register(fallback)
    router.errors.register(
        telegram_refused, ExceptionTypeFilter(TelegramForbiddenError, TelegramBadRequest)
    )
    return router
