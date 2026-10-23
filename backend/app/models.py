from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_products_chat_message"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    image_key: Mapped[str] = mapped_column(String(512))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
