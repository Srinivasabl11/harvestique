"""admin-controlled tester access

Revision ID: 0016_tester_access
Revises: 0015_crop_catalogue_metadata
Create Date: 2026-10-15 10:00:00

Additive only. users.access_status (approved / pending / suspended / revoked) and access_changed_at. Every existing
account is set to 'approved' by the server default, so nobody loses access; only new sign-ups can start as 'pending'
(NEW_ACCOUNT_ACCESS=pending).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_tester_access"
down_revision: str | None = "0015_crop_catalogue_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("access_status", sa.String(length=16), server_default="approved", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_users_access_status"), "users", "access_status IN ('approved', 'pending', 'suspended', 'revoked')"
    )
    op.add_column("users", sa.Column("access_changed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "access_changed_at")
    op.drop_constraint(op.f("ck_users_access_status"), "users", type_="check")
    op.drop_column("users", "access_status")
