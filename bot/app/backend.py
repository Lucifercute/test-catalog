from enum import StrEnum

import httpx


class CreateResult(StrEnum):
    CREATED = "created"
    EXISTS = "exists"


class BackendUnavailable(Exception):
    """Transient: let the webhook fail so Telegram redelivers the update."""


class BackendError(Exception):
    """Permanent and not the user's fault (bad token, unexpected 4xx): retrying won't help."""


class ProductRejected(Exception):
    """The backend refused the product itself; the reason is safe to show the admin."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


REJECT_REASONS = {
    413: "Фото слишком большое.",
    415: "Неподдерживаемый формат фото.",
    422: "Название должно быть от 1 до 255 символов.",
}


class BackendClient:
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._token = internal_token

    async def create_product(
        self, *, title: str, chat_id: int, message_id: int, image: bytes
    ) -> CreateResult:
        """Idempotent by (chat_id, message_id), so a redelivered update is safe to resend."""
        try:
            response = await self._http.post(
                "products",
                headers={"X-Internal-Token": self._token},
                data={"title": title, "chat_id": str(chat_id), "message_id": str(message_id)},
                # Telegram re-encodes every photo as JPEG.
                files={"image": ("photo.jpg", image, "image/jpeg")},
            )
        except httpx.TransportError as exc:
            raise BackendUnavailable(f"backend request failed: {exc!r}") from exc

        status = response.status_code
        if status == 201:
            return CreateResult.CREATED
        if status == 200:
            return CreateResult.EXISTS
        if status in REJECT_REASONS:
            raise ProductRejected(REJECT_REASONS[status])
        if status == 429 or status >= 500:
            raise BackendUnavailable(f"backend responded {status}")
        raise BackendError(f"backend responded {status}: {response.text[:200]}")
