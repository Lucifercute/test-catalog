"""create products

Revision ID: 0001
Revises:
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("image_key", sa.String(length=512), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_products_chat_message"),
    )
    op.create_index("ix_products_created_at", "products", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_products_created_at", table_name="products")
    op.drop_table("products")
