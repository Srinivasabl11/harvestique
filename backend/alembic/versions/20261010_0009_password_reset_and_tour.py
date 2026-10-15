"""password reset codes and the first-login tour

Revision ID: 0009_password_reset_tour
Revises: 0008_phone_verification
Create Date: 2026-10-10 02:30:00

Additive only. otp_challenges.purpose also accepts 'password_reset'; users get tour_version_seen (0 = the guided tour
was never shown, so every existing account sees it once after its next sign-in).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_password_reset_tour"
down_revision: str | None = "0008_phone_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_otp_challenges_otp_purpose"), "otp_challenges", type_="check")
    op.create_check_constraint(
        op.f("ck_otp_challenges_otp_purpose"), "otp_challenges", "purpose IN ('register', 'login', 'password_reset')"
    )
    op.add_column("users", sa.Column("tour_version_seen", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "tour_version_seen")
    op.execute("DELETE FROM otp_challenges WHERE purpose = 'password_reset'")
    op.drop_constraint(op.f("ck_otp_challenges_otp_purpose"), "otp_challenges", type_="check")
    op.create_check_constraint(
        op.f("ck_otp_challenges_otp_purpose"), "otp_challenges", "purpose IN ('register', 'login')"
    )
