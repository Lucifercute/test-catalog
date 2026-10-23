from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


async def add_products(session: AsyncSession, count: int) -> None:
    session.add_all(
        Product(
            title=f"Product {i}",
            image_key=f"products/{i}.jpg",
            chat_id=1,
            message_id=i,
            created_at=BASE_TIME + timedelta(minutes=i),
        )
        for i in range(count)
    )
    await session.commit()


async def test_list_empty(client: AsyncClient) -> None:
    response = await client.get("/products")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_newest_first(client: AsyncClient, session: AsyncSession) -> None:
    await add_products(session, 3)

    response = await client.get("/products")

    assert response.status_code == 200
    assert [p["title"] for p in response.json()] == ["Product 2", "Product 1", "Product 0"]


async def test_image_url_uses_media_base_url(client: AsyncClient, session: AsyncSession) -> None:
    await add_products(session, 1)

    (product,) = (await client.get("/products")).json()

    # MEDIA_BASE_URL in tests ends with "/": no double slash expected.
    assert product["image_url"] == "http://media.test/media/products/0.jpg"
    assert "image_key" not in product
    assert "chat_id" not in product


async def test_list_pagination(client: AsyncClient, session: AsyncSession) -> None:
    await add_products(session, 5)

    response = await client.get("/products", params={"limit": 2, "offset": 1})

    assert [p["title"] for p in response.json()] == ["Product 3", "Product 2"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_list_rejects_bad_pagination(client: AsyncClient, params: dict[str, int]) -> None:
    response = await client.get("/products", params=params)

    assert response.status_code == 422


async def test_chat_message_is_unique(session: AsyncSession) -> None:
    await add_products(session, 1)
    session.add(Product(title="Dup", image_key="products/dup.jpg", chat_id=1, message_id=0))

    with pytest.raises(IntegrityError):
        await session.commit()
