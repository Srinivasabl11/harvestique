"""produce quality grading (A/B/C) of recorded harvests

Revision ID: 0018_produce_grading
Revises: 0017_password_only_auth
Create Date: 2026-10-15 23:00:00

Additive only: a new, empty table produce_gradings (one row per recorded harvest, written only when a farmer grades
it). No existing table or row is touched. Downgrade drops only this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_produce_grading"
down_revision: str | None = "0017_password_only_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _grade(name: str) -> sa.Enum:
    return sa.Enum("A", "B", "C", name=name, native_enum=False, create_constraint=True, length=2)


def upgrade() -> None:
    json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "produce_gradings",
        sa.Column("harvest_actual_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("profile", sa.String(length=16), nullable=False),
        sa.Column("criteria_version", sa.Integer(), nullable=False),
        sa.Column("proposal_status", sa.String(length=24), nullable=True),
        sa.Column("proposal_reason", sa.String(length=40), nullable=True),
        sa.Column("proposed_levels", json, nullable=True),
        sa.Column("proposed_grade", _grade("proposed_grade"), nullable=True),
        sa.Column("proposal_details", json, nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("levels", json, nullable=True),
        sa.Column("criteria_grade", _grade("criteria_grade"), nullable=True),
        sa.Column("grade", _grade("produce_grade"), nullable=True),
        sa.Column("grade_source", sa.String(length=16), nullable=True),
        sa.Column("override_reason", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(grade IS NULL) = (confirmed_at IS NULL)", name=op.f("ck_produce_gradings_grade_iff_confirmed")
        ),
        sa.CheckConstraint(
            "(grade IS NULL) = (criteria_grade IS NULL)", name=op.f("ck_produce_gradings_criteria_grade_with_grade")
        ),
        sa.CheckConstraint(
            "grade IS NULL OR grade >= criteria_grade", name=op.f("ck_produce_gradings_grade_not_above_criteria")
        ),
        sa.CheckConstraint(
            "grade_source IS NULL OR grade_source IN ('manual', 'photo_confirmed', 'photo_corrected')",
            name=op.f("ck_produce_gradings_grade_source_known"),
        ),
        sa.CheckConstraint(
            "proposal_status IS NULL OR proposal_status IN "
            "('proposed', 'needs_more_evidence', 'retake_photo', 'unavailable')",
            name=op.f("ck_produce_gradings_proposal_status_known"),
        ),
        sa.ForeignKeyConstraint(
            ["harvest_actual_id"],
            ["harvest_actuals.id"],
            name=op.f("fk_produce_gradings_harvest_actual_id_harvest_actuals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_produce_gradings_owner_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name=op.f("fk_produce_gradings_confirmed_by_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_produce_gradings")),
        sa.UniqueConstraint("harvest_actual_id", name="uq_produce_gradings_harvest_actual_id"),
    )
    op.create_index(op.f("ix_produce_gradings_owner_id"), "produce_gradings", ["owner_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_produce_gradings_owner_id"), table_name="produce_gradings")
    op.drop_table("produce_gradings")
