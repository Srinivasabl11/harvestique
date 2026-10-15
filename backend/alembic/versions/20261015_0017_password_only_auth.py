"""password-only sign-in: admin password resets

Revision ID: 0017_password_only_auth
Revises: 0016_tester_access
Create Date: 2026-10-15 18:00:00

Additive only. users.must_change_password is set when an admin issues a temporary password; the person must choose a
new one before they get a session. Every existing account gets false, so nobody is affected. SMS one-time codes are
no longer used: the otp_challenges table is kept untouched as history (nothing writes to it any more).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_password_only_auth"
down_revision: str | None = "0016_tester_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
