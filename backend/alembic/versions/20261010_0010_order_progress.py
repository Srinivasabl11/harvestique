"""farmer progress on accepted supply requests (preparing -> ready)

Revision ID: 0010_order_progress
Revises: 0009_password_reset_tour
Create Date: 2026-10-10 04:00:00

Additive only: two nullable columns; existing participations keep NULL (no progress reported yet).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0010_order_progress'
down_revision: str | None = '0009_password_reset_tour'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'farmer_participations',
        sa.Column('progress', sa.Enum('preparing', 'ready', name='farmer_progress', native_enum=False, create_constraint=True, length=16), nullable=True),
    )
    op.add_column('farmer_participations', sa.Column('progress_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('farmer_participations', 'progress_at')
    op.drop_column('farmer_participations', 'progress')
