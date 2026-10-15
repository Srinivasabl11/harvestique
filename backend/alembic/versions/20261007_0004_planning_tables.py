"""crop plans

Revision ID: 0004_planning
Revises: 0003_farming
Create Date: 2026-10-07 08:48:41.339158
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0004_planning'
down_revision: str | None = '0003_farming'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('crop_plans',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('farm_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('season', sa.Enum('kharif', 'rabi', 'summer', 'year_round', name='plan_season', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('available_land_acres', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('budget_inr', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('available_water_kl', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('available_labour_person_days', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('available_labour_person_days IS NULL OR available_labour_person_days > 0', name=op.f('ck_crop_plans_labour_positive')),
    sa.CheckConstraint('available_land_acres > 0', name=op.f('ck_crop_plans_land_positive')),
    sa.CheckConstraint('available_water_kl IS NULL OR available_water_kl > 0', name=op.f('ck_crop_plans_water_positive')),
    sa.CheckConstraint('budget_inr IS NULL OR budget_inr > 0', name=op.f('ck_crop_plans_budget_positive')),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], name=op.f('fk_crop_plans_farm_id_farms'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_crop_plans_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crop_plans')),
    sa.UniqueConstraint('owner_id', 'name', name='uq_crop_plans_owner_id_name')
    )
    op.create_index(op.f('ix_crop_plans_farm_id'), 'crop_plans', ['farm_id'], unique=False)
    op.create_table('crop_plan_items',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('crop_id', sa.Uuid(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('crop_name', sa.String(length=80), nullable=False),
    sa.Column('area_acres', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('sowing_date', sa.Date(), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=False),
    sa.Column('harvest_window_days', sa.Integer(), nullable=False),
    sa.Column('batches', sa.Integer(), nullable=False),
    sa.Column('batch_interval_days', sa.Integer(), nullable=True),
    sa.Column('yield_low_kg', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('yield_expected_kg', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('yield_high_kg', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('price_low', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('price_expected', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('price_high', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('seed_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('fertilizer_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('pesticide_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('irrigation_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('machinery_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('other_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('labour_person_days', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('labour_wage', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('fixed_cost', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('cost_overrun_pct', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('water_kl_per_acre', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('demand_level', sa.Enum('low', 'medium', 'high', name='demand_level', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('demand_quantity_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('declared_risk', sa.Enum('low', 'medium', 'high', name='declared_risk', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('estimate_basis', sa.Enum('own_records', 'local_knowledge', 'assumption', name='estimate_basis', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('area_acres > 0', name=op.f('ck_crop_plan_items_area_positive')),
    sa.CheckConstraint('batches = 1 OR (batch_interval_days IS NOT NULL AND batch_interval_days >= 1)', name=op.f('ck_crop_plan_items_batch_interval_required')),
    sa.CheckConstraint('batches BETWEEN 1 AND 12', name=op.f('ck_crop_plan_items_batches_range')),
    sa.CheckConstraint('cost_overrun_pct IS NULL OR cost_overrun_pct >= 0', name=op.f('ck_crop_plan_items_overrun_non_negative')),
    sa.CheckConstraint('demand_quantity_kg IS NULL OR demand_quantity_kg > 0', name=op.f('ck_crop_plan_items_demand_positive')),
    sa.CheckConstraint('duration_days > 0', name=op.f('ck_crop_plan_items_duration_positive')),
    sa.CheckConstraint('harvest_window_days BETWEEN 1 AND 365', name=op.f('ck_crop_plan_items_harvest_window_range')),
    sa.CheckConstraint('price_low >= 0 AND price_low <= price_expected AND price_expected <= price_high AND price_expected > 0', name=op.f('ck_crop_plan_items_price_ordered')),
    sa.CheckConstraint('seed_cost >= 0 AND fertilizer_cost >= 0 AND pesticide_cost >= 0 AND irrigation_cost >= 0 AND machinery_cost >= 0 AND other_cost >= 0 AND labour_person_days >= 0 AND labour_wage >= 0 AND fixed_cost >= 0', name=op.f('ck_crop_plan_items_costs_non_negative')),
    sa.CheckConstraint('water_kl_per_acre IS NULL OR water_kl_per_acre >= 0', name=op.f('ck_crop_plan_items_water_non_negative')),
    sa.CheckConstraint('yield_low_kg >= 0 AND yield_low_kg <= yield_expected_kg AND yield_expected_kg <= yield_high_kg AND yield_expected_kg > 0', name=op.f('ck_crop_plan_items_yield_ordered')),
    sa.ForeignKeyConstraint(['crop_id'], ['crops.id'], name=op.f('fk_crop_plan_items_crop_id_crops'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plan_id'], ['crop_plans.id'], name=op.f('fk_crop_plan_items_plan_id_crop_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crop_plan_items'))
    )
    op.create_index(op.f('ix_crop_plan_items_crop_id'), 'crop_plan_items', ['crop_id'], unique=False)
    op.create_index('ix_crop_plan_items_plan_id_position', 'crop_plan_items', ['plan_id', 'position'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_crop_plan_items_plan_id_position', table_name='crop_plan_items')
    op.drop_index(op.f('ix_crop_plan_items_crop_id'), table_name='crop_plan_items')
    op.drop_table('crop_plan_items')
    op.drop_index(op.f('ix_crop_plans_farm_id'), table_name='crop_plans')
    op.drop_table('crop_plans')
