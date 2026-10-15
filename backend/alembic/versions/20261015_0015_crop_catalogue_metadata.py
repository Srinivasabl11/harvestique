"""crop catalogue metadata: scientific name, aliases, crop group

Revision ID: 0015_crop_catalogue_metadata
Revises: 0014_market_prices
Create Date: 2026-10-15 00:30:00

Three new, optional columns on `crops`. Additive: no row, id, name or Kannada name changes here (values are filled
for EMPTY fields by `python -m app.cli.seed_crops --reconcile`). Downgrade drops only these columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_crop_catalogue_metadata"
down_revision: str | None = "0014_market_prices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GROUPS = (
    "'cereals', 'millets', 'pulses', 'oilseeds', 'vegetables', 'fruits', 'spices', 'roots_tubers', 'plantation', "
    "'beverage', 'fibre', 'sugar_starch', 'fodder', 'medicinal_aromatic', 'ornamental', 'agroforestry', 'mushrooms', "
    "'other'"
)


def upgrade() -> None:
    op.add_column("crops", sa.Column("scientific_name", sa.String(length=120), nullable=True))
    op.add_column(
        "crops",
        sa.Column(
            "aliases",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column("crops", sa.Column("crop_group", sa.String(length=24), nullable=True))
    op.create_check_constraint(op.f("ck_crops_crop_group"), "crops", f"crop_group IN ({GROUPS})")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_crops_crop_group"), "crops", type_="check")
    op.drop_column("crops", "crop_group")
    op.drop_column("crops", "aliases")
    op.drop_column("crops", "scientific_name")
