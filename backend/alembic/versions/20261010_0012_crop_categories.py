"""fodder and medicinal crop categories

Revision ID: 0012_crop_categories
Revises: 0011_harvest_correction
Create Date: 2026-10-10 04:00:00

Additive only: crops.category also accepts 'fodder' and 'medicinal'. Existing crops and their ids are unchanged; the
expanded starter catalogue is inserted by `python -m app.cli.seed_crops`, which skips names that already exist.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_crop_categories"
down_revision: str | None = "0011_harvest_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "'vegetable', 'fruit', 'cereal', 'pulse', 'oilseed', 'spice', 'cash_crop', 'flower', 'other'"
NEW = "'vegetable', 'fruit', 'cereal', 'pulse', 'oilseed', 'spice', 'cash_crop', 'flower', 'fodder', 'medicinal', 'other'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_crops_crop_category"), "crops", type_="check")
    op.create_check_constraint(op.f("ck_crops_crop_category"), "crops", f"category IN ({NEW})")


def downgrade() -> None:
    # crops in the new categories keep existing (they may be referenced by crop cycles); they become 'other'
    op.execute("UPDATE crops SET category = 'other' WHERE category IN ('fodder', 'medicinal')")
    op.drop_constraint(op.f("ck_crops_crop_category"), "crops", type_="check")
    op.create_check_constraint(op.f("ck_crops_crop_category"), "crops", f"category IN ({OLD})")
