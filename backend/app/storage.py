from __future__ import annotations

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session

from app.config import Settings

if TYPE_CHECKING:
    # Stubs are a dev dependency; not installed in the runtime image.
    from types_aiobotocore_s3 import S3Client

# MIME type -> file extension of the stored object.
ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


async def create_s3_client(settings: Settings, stack: AsyncExitStack) -> S3Client:
    # One client (and connection pool) per process; closed when `stack` exits.
    return await stack.enter_async_context(
        get_session().create_client(
            "s3",
            endpoint_url=settings.minio_endpoint_url,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password.get_secret_value(),
            region_name="us-east-1",
            config=AioConfig(s3={"addressing_style": "path"}),
        )
    )


def sniff_image_type(data: bytes) -> str | None:
    """Detect the real type by magic bytes; the client's Content-Type is not trusted alone."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_key(chat_id: int, message_id: int, ext: str) -> str:
    # Deterministic: a retried upload overwrites the same object instead of adding a new one.
    return f"products/{chat_id}/{message_id}.{ext}"


async def put_image(
    client: S3Client, bucket: str, key: str, data: bytes, content_type: str
) -> None:
    await client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
