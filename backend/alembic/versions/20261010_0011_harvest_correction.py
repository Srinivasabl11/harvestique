"""audit trail for corrected harvests

Revision ID: 0011_harvest_correction
Revises: 0010_order_progress
Create Date: 2026-10-10 05:00:00

Additive only: three nullable columns on harvest_actuals; existing harvests keep NULL (never corrected).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0011_harvest_correction'
down_revision: str | None = '0010_order_progress'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('harvest_actuals', sa.Column('previous_quantity_kg', sa.Numeric(precision=14, scale=3), nullable=True))
    op.add_column('harvest_actuals', sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('harvest_actuals', sa.Column('correction_reason', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('harvest_actuals', 'correction_reason')
    op.drop_column('harvest_actuals', 'corrected_at')
    op.drop_column('harvest_actuals', 'previous_quantity_kg')
