"""market prices (AGMARKNET via data.gov.in)

Revision ID: 0014_market_prices
Revises: 0013_plantation_category
Create Date: 2026-10-14 19:30:00

A new, empty cache table for mandi prices fetched from data.gov.in (the API serves only the current day). Additive:
no existing table or row is touched. Downgrade drops only this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_market_prices"
down_revision: str | None = "0013_plantation_category"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=60), nullable=False),
        sa.Column("district", sa.String(length=80), nullable=False),
        sa.Column("market", sa.String(length=120), nullable=False),
        sa.Column("commodity", sa.String(length=80), nullable=False),
        sa.Column("variety", sa.String(length=80), nullable=False),
        sa.Column("grade", sa.String(length=40), nullable=False),
        sa.Column("arrival_date", sa.Date(), nullable=False),
        sa.Column("min_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("modal_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "min_price > 0 AND min_price <= modal_price AND modal_price <= max_price",
            name=op.f("ck_market_prices_prices_ordered"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_prices")),
        sa.UniqueConstraint(
            "state", "district", "market", "commodity", "variety", "grade", "arrival_date", name="uq_market_prices_report"
        ),
    )
    op.create_index(op.f("ix_market_prices_state"), "market_prices", ["state"])
    op.create_index(op.f("ix_market_prices_commodity"), "market_prices", ["commodity"])


def downgrade() -> None:
    op.drop_index(op.f("ix_market_prices_commodity"), table_name="market_prices")
    op.drop_index(op.f("ix_market_prices_state"), table_name="market_prices")
    op.drop_table("market_prices")
