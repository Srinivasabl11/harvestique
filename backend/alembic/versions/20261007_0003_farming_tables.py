"""farm and crop management

Revision ID: 0003_farming
Revises: 0002_identity
Create Date: 2026-10-07 08:12:16.920437
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0003_farming'
down_revision: str | None = '0002_identity'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('crops',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('local_name', sa.String(length=80), nullable=True),
    sa.Column('category', sa.Enum('vegetable', 'fruit', 'cereal', 'pulse', 'oilseed', 'spice', 'cash_crop', 'flower', 'other', name='crop_category', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('typical_duration_days', sa.Integer(), nullable=False),
    sa.Column('season', sa.Enum('kharif', 'rabi', 'summer', 'year_round', name='crop_season', native_enum=False, create_constraint=True, length=24), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('typical_duration_days > 0 AND typical_duration_days <= 3650', name=op.f('ck_crops_duration_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crops')),
    sa.UniqueConstraint('name', name=op.f('uq_crops_name'))
    )
    op.create_table('farms',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('village', sa.String(length=100), nullable=True),
    sa.Column('district', sa.String(length=100), nullable=True),
    sa.Column('state', sa.String(length=100), nullable=True),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('total_area_acres', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(latitude IS NULL) = (longitude IS NULL)', name=op.f('ck_farms_coordinates_paired')),
    sa.CheckConstraint('latitude BETWEEN -90 AND 90', name=op.f('ck_farms_latitude_range')),
    sa.CheckConstraint('longitude BETWEEN -180 AND 180', name=op.f('ck_farms_longitude_range')),
    sa.CheckConstraint('total_area_acres > 0', name=op.f('ck_farms_area_positive')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_farms_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_farms')),
    sa.UniqueConstraint('owner_id', 'name', name='uq_farms_owner_id_name')
    )
    op.create_table('farm_plots',
    sa.Column('farm_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('area_acres', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('soil_type', sa.Enum('red', 'black', 'alluvial', 'laterite', 'sandy', 'loamy', 'clay', 'other', name='soil_type', native_enum=False, create_constraint=True, length=24), nullable=True),
    sa.Column('irrigation_type', sa.Enum('rainfed', 'borewell', 'canal', 'drip', 'sprinkler', 'tank', 'river', 'other', name='irrigation_type', native_enum=False, create_constraint=True, length=24), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('area_acres > 0', name=op.f('ck_farm_plots_area_positive')),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], name=op.f('fk_farm_plots_farm_id_farms'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_farm_plots')),
    sa.UniqueConstraint('farm_id', 'name', name='uq_farm_plots_farm_id_name')
    )
    op.create_table('crop_cycles',
    sa.Column('plot_id', sa.Uuid(), nullable=False),
    sa.Column('crop_id', sa.Uuid(), nullable=False),
    sa.Column('variety', sa.String(length=80), nullable=True),
    sa.Column('status', sa.Enum('planned', 'growing', 'harvested', 'abandoned', name='cycle_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('area_acres', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('sowing_date', sa.Date(), nullable=False),
    sa.Column('expected_harvest_date', sa.Date(), nullable=True),
    sa.Column('actual_harvest_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'harvested') = (actual_harvest_date IS NOT NULL)", name=op.f('ck_crop_cycles_harvest_date_iff_harvested')),
    sa.CheckConstraint('actual_harvest_date IS NULL OR actual_harvest_date >= sowing_date', name=op.f('ck_crop_cycles_actual_not_before_sowing')),
    sa.CheckConstraint('area_acres > 0', name=op.f('ck_crop_cycles_area_positive')),
    sa.CheckConstraint('expected_harvest_date IS NULL OR expected_harvest_date > sowing_date', name=op.f('ck_crop_cycles_expected_after_sowing')),
    sa.ForeignKeyConstraint(['crop_id'], ['crops.id'], name=op.f('fk_crop_cycles_crop_id_crops'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plot_id'], ['farm_plots.id'], name=op.f('fk_crop_cycles_plot_id_farm_plots'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crop_cycles'))
    )
    op.create_index(op.f('ix_crop_cycles_crop_id'), 'crop_cycles', ['crop_id'], unique=False)
    op.create_index('ix_crop_cycles_plot_id_sowing_date', 'crop_cycles', ['plot_id', 'sowing_date'], unique=False)
    op.create_table('crop_observations',
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=False),
    sa.Column('observed_on', sa.Date(), nullable=False),
    sa.Column('growth_stage', sa.Enum('germination', 'vegetative', 'flowering', 'fruiting', 'maturity', name='growth_stage', native_enum=False, create_constraint=True, length=24), nullable=True),
    sa.Column('health_status', sa.Enum('healthy', 'stressed', 'pest_affected', 'disease_affected', 'damaged', name='health_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('estimated_loss_percent', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('estimated_loss_percent IS NULL OR (estimated_loss_percent >= 0 AND estimated_loss_percent <= 100)', name=op.f('ck_crop_observations_loss_percent_range')),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_crop_observations_crop_cycle_id_crop_cycles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crop_observations'))
    )
    op.create_index('ix_crop_observations_crop_cycle_id_observed_on', 'crop_observations', ['crop_cycle_id', 'observed_on'], unique=False)
    op.create_table('farm_activities',
    sa.Column('farm_id', sa.Uuid(), nullable=False),
    sa.Column('plot_id', sa.Uuid(), nullable=True),
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=True),
    sa.Column('activity_type', sa.Enum('land_preparation', 'sowing', 'irrigation', 'fertilizing', 'pest_control', 'weeding', 'pruning', 'harvesting', 'other', name='activity_type', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('activity_date', sa.Date(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_farm_activities_crop_cycle_id_crop_cycles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], name=op.f('fk_farm_activities_farm_id_farms'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['plot_id'], ['farm_plots.id'], name=op.f('fk_farm_activities_plot_id_farm_plots'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_farm_activities'))
    )
    op.create_index(op.f('ix_farm_activities_crop_cycle_id'), 'farm_activities', ['crop_cycle_id'], unique=False)
    op.create_index('ix_farm_activities_farm_id_activity_date', 'farm_activities', ['farm_id', 'activity_date'], unique=False)
    op.create_index(op.f('ix_farm_activities_plot_id'), 'farm_activities', ['plot_id'], unique=False)
    op.create_table('farm_expenses',
    sa.Column('farm_id', sa.Uuid(), nullable=False),
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=True),
    sa.Column('category', sa.Enum('seed', 'fertilizer', 'pesticide', 'labour', 'irrigation', 'machinery', 'transport', 'other', name='expense_category', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('expense_date', sa.Date(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name=op.f('ck_farm_expenses_amount_positive')),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_farm_expenses_crop_cycle_id_crop_cycles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], name=op.f('fk_farm_expenses_farm_id_farms'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_farm_expenses'))
    )
    op.create_index(op.f('ix_farm_expenses_crop_cycle_id'), 'farm_expenses', ['crop_cycle_id'], unique=False)
    op.create_index('ix_farm_expenses_farm_id_expense_date', 'farm_expenses', ['farm_id', 'expense_date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_farm_expenses_farm_id_expense_date', table_name='farm_expenses')
    op.drop_index(op.f('ix_farm_expenses_crop_cycle_id'), table_name='farm_expenses')
    op.drop_table('farm_expenses')
    op.drop_index(op.f('ix_farm_activities_plot_id'), table_name='farm_activities')
    op.drop_index('ix_farm_activities_farm_id_activity_date', table_name='farm_activities')
    op.drop_index(op.f('ix_farm_activities_crop_cycle_id'), table_name='farm_activities')
    op.drop_table('farm_activities')
    op.drop_index('ix_crop_observations_crop_cycle_id_observed_on', table_name='crop_observations')
    op.drop_table('crop_observations')
    op.drop_index('ix_crop_cycles_plot_id_sowing_date', table_name='crop_cycles')
    op.drop_index(op.f('ix_crop_cycles_crop_id'), table_name='crop_cycles')
    op.drop_table('crop_cycles')
    op.drop_table('farm_plots')
    op.drop_table('farms')
    op.drop_table('crops')
