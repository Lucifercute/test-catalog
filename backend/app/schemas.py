from datetime import datetime

from pydantic import BaseModel

from app.models import Product


class ProductOut(BaseModel):
    id: int
    title: str
    image_url: str
    created_at: datetime

    @classmethod
    def from_model(cls, product: Product, media_base_url: str) -> "ProductOut":
        return cls(
            id=product.id,
            title=product.title,
            image_url=f"{media_base_url.rstrip('/')}/{product.image_key}",
            created_at=product.created_at,
        )
