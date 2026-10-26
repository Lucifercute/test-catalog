from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message, User

from app.config import TelegramSettings


def is_admin(user: User | None, settings: TelegramSettings) -> bool:
    return user is not None and user.id in settings.admin_ids


class IsAdmin(Filter):
    """`settings` is injected by aiogram from the dispatcher's workflow data."""

    async def __call__(self, event: Message | CallbackQuery, settings: TelegramSettings) -> bool:
        return is_admin(event.from_user, settings)
