"""plantation crop category

Revision ID: 0013_plantation_category
Revises: 0012_crop_categories
Create Date: 2026-10-13 23:00:00

crops.category also accepts 'plantation'. Coconut, Arecanut and Coffee (added as 'cash_crop' by the stage-3 catalogue)
move to it, but only where an admin has not changed their category; their ids, and every crop cycle that uses them,
are unchanged. New plantation crops and minor millets are inserted by `python -m app.cli.seed_crops`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_plantation_category"
down_revision: str | None = "0012_crop_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "'vegetable', 'fruit', 'cereal', 'pulse', 'oilseed', 'spice', 'cash_crop', 'flower', 'fodder', 'medicinal', 'other'"
)
NEW = (
    "'vegetable', 'fruit', 'cereal', 'pulse', 'oilseed', 'spice', 'cash_crop', 'plantation', 'flower', 'fodder', "
    "'medicinal', 'other'"
)
MOVED = "'Coconut', 'Arecanut', 'Coffee'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_crops_crop_category"), "crops", type_="check")
    op.create_check_constraint(op.f("ck_crops_crop_category"), "crops", f"category IN ({NEW})")
    op.execute(f"UPDATE crops SET category = 'plantation' WHERE name IN ({MOVED}) AND category = 'cash_crop'")


def downgrade() -> None:
    op.execute("UPDATE crops SET category = 'cash_crop' WHERE category = 'plantation'")
    op.drop_constraint(op.f("ck_crops_crop_category"), "crops", type_="check")
    op.create_check_constraint(op.f("ck_crops_crop_category"), "crops", f"category IN ({OLD})")
