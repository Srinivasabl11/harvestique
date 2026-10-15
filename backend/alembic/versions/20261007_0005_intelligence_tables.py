"""intelligence

Revision ID: 0005_intelligence
Revises: 0004_planning
Create Date: 2026-10-07 09:37:05.916902
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005_intelligence'
down_revision: str | None = '0004_planning'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('weather_daily',
    sa.Column('lat_key', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('lon_key', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('kind', sa.Enum('observed', 'forecast', name='weather_kind', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('tmin_c', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('tmax_c', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('rain_mm', sa.Numeric(precision=7, scale=2), nullable=False),
    sa.Column('et0_mm', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_weather_daily')),
    sa.UniqueConstraint('lat_key', 'lon_key', 'day', 'kind', name='uq_weather_daily_point_day_kind')
    )
    op.create_table('calibration_profiles',
    sa.Column('scope', sa.String(length=64), nullable=False),
    sa.Column('crop_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('sample_size', sa.Integer(), nullable=False),
    sa.Column('sufficient', sa.Boolean(), nullable=False),
    sa.Column('coverage', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('mape', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('bias_factor', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('interval_scale', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('date_mae_days', sa.Numeric(precision=8, scale=1), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('bias_factor > 0 AND interval_scale > 0', name=op.f('ck_calibration_profiles_factors_positive')),
    sa.CheckConstraint('sample_size >= 0', name=op.f('ck_calibration_profiles_sample_size_non_negative')),
    sa.ForeignKeyConstraint(['crop_id'], ['crops.id'], name=op.f('fk_calibration_profiles_crop_id_crops'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calibration_profiles')),
    sa.UniqueConstraint('scope', 'version', name='uq_calibration_profiles_scope_version')
    )
    op.create_index(op.f('ix_calibration_profiles_crop_id'), 'calibration_profiles', ['crop_id'], unique=False)
    op.create_table('harvest_actuals',
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('harvest_start_date', sa.Date(), nullable=False),
    sa.Column('recorded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('quantity_kg >= 0', name=op.f('ck_harvest_actuals_quantity_non_negative')),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_harvest_actuals_crop_cycle_id_crop_cycles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_harvest_actuals_recorded_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_harvest_actuals')),
    sa.UniqueConstraint('crop_cycle_id', name=op.f('uq_harvest_actuals_crop_cycle_id'))
    )
    op.create_table('yield_predictions',
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('ok', 'insufficient_data', name='prediction_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('model_name', sa.String(length=40), nullable=False),
    sa.Column('model_version', sa.String(length=20), nullable=False),
    sa.Column('p10_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('p50_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('p90_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('harvest_start_p10', sa.Date(), nullable=False),
    sa.Column('harvest_start_p50', sa.Date(), nullable=False),
    sa.Column('harvest_start_p90', sa.Date(), nullable=False),
    sa.Column('harvest_end_p90', sa.Date(), nullable=False),
    sa.Column('confidence_score', sa.Numeric(precision=4, scale=1), nullable=False),
    sa.Column('confidence_level', sa.String(length=16), nullable=False),
    sa.Column('confidence_basis', sa.String(length=16), nullable=False),
    sa.Column('risk_score', sa.Numeric(precision=4, scale=1), nullable=True),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('weather_status', sa.Enum('fresh', 'stale', 'unavailable', name='weather_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('calibration_profile_id', sa.Uuid(), nullable=True),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('(p50_kg IS NULL) OR (p10_kg >= 0 AND p10_kg <= p50_kg AND p50_kg <= p90_kg)', name=op.f('ck_yield_predictions_quantiles_ordered')),
    sa.CheckConstraint('confidence_score BETWEEN 0 AND 100', name=op.f('ck_yield_predictions_confidence_range')),
    sa.CheckConstraint('harvest_start_p10 <= harvest_start_p50 AND harvest_start_p50 <= harvest_start_p90', name=op.f('ck_yield_predictions_dates_ordered')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_yield_predictions_version_positive')),
    sa.ForeignKeyConstraint(['calibration_profile_id'], ['calibration_profiles.id'], name=op.f('fk_yield_predictions_calibration_profile_id_calibration_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_yield_predictions_crop_cycle_id_crop_cycles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_yield_predictions')),
    sa.UniqueConstraint('crop_cycle_id', 'version', name='uq_yield_predictions_cycle_version')
    )
    op.create_index(op.f('ix_yield_predictions_crop_cycle_id'), 'yield_predictions', ['crop_cycle_id'], unique=False)
    op.create_table('inventory_lots',
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('prediction_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('open', 'at_risk', 'harvested', 'cancelled', name='lot_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('p10_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('p50_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('p90_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('actual_kg', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('committable_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('committed_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('available_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('shortfall_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('basis', sa.String(length=80), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('committable_kg >= 0 AND committed_kg >= 0 AND available_kg >= 0 AND shortfall_kg >= 0', name=op.f('ck_inventory_lots_quantities_non_negative')),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_inventory_lots_crop_cycle_id_crop_cycles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_inventory_lots_owner_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prediction_id'], ['yield_predictions.id'], name=op.f('fk_inventory_lots_prediction_id_yield_predictions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_lots')),
    sa.UniqueConstraint('crop_cycle_id', name=op.f('uq_inventory_lots_crop_cycle_id'))
    )
    op.create_index(op.f('ix_inventory_lots_owner_id'), 'inventory_lots', ['owner_id'], unique=False)
    op.create_table('prediction_feedback',
    sa.Column('prediction_id', sa.Uuid(), nullable=False),
    sa.Column('harvest_actual_id', sa.Uuid(), nullable=False),
    sa.Column('signed_error_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('abs_error_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('abs_pct_error', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('within_interval', sa.Boolean(), nullable=False),
    sa.Column('pinball_loss', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('date_error_days', sa.Integer(), nullable=True),
    sa.Column('date_within_window', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['harvest_actual_id'], ['harvest_actuals.id'], name=op.f('fk_prediction_feedback_harvest_actual_id_harvest_actuals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prediction_id'], ['yield_predictions.id'], name=op.f('fk_prediction_feedback_prediction_id_yield_predictions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_feedback')),
    sa.UniqueConstraint('prediction_id', name=op.f('uq_prediction_feedback_prediction_id'))
    )
    op.create_index(op.f('ix_prediction_feedback_harvest_actual_id'), 'prediction_feedback', ['harvest_actual_id'], unique=False)
    op.create_table('inventory_reservations',
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('booking_key', sa.String(length=80), nullable=False),
    sa.Column('status', sa.Enum('active', 'released', 'fulfilled', name='reservation_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('note', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity_kg > 0', name=op.f('ck_inventory_reservations_quantity_positive')),
    sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], name=op.f('fk_inventory_reservations_lot_id_inventory_lots'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_reservations')),
    sa.UniqueConstraint('lot_id', 'booking_key', name='uq_inventory_reservations_lot_id_booking_key')
    )
    op.create_index(op.f('ix_inventory_reservations_lot_id'), 'inventory_reservations', ['lot_id'], unique=False)
    op.add_column('crops', sa.Column('reference_yield_kg_per_acre', sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column('crops', sa.Column('reference_yield_cv', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('crops', sa.Column('water_need_mm', sa.Numeric(precision=8, scale=1), nullable=True))
    # Autogenerate does not emit CHECK constraints for existing tables: added by hand.
    op.create_check_constraint(op.f('ck_crops_reference_yield_positive'), 'crops', 'reference_yield_kg_per_acre IS NULL OR reference_yield_kg_per_acre > 0')
    op.create_check_constraint(op.f('ck_crops_reference_cv_range'), 'crops', 'reference_yield_cv IS NULL OR reference_yield_cv BETWEEN 0.01 AND 2')
    op.create_check_constraint(op.f('ck_crops_water_need_positive'), 'crops', 'water_need_mm IS NULL OR water_need_mm > 0')


def downgrade() -> None:
    op.drop_constraint(op.f('ck_crops_water_need_positive'), 'crops', type_='check')
    op.drop_constraint(op.f('ck_crops_reference_cv_range'), 'crops', type_='check')
    op.drop_constraint(op.f('ck_crops_reference_yield_positive'), 'crops', type_='check')
    op.drop_column('crops', 'water_need_mm')
    op.drop_column('crops', 'reference_yield_cv')
    op.drop_column('crops', 'reference_yield_kg_per_acre')
    op.drop_index(op.f('ix_inventory_reservations_lot_id'), table_name='inventory_reservations')
    op.drop_table('inventory_reservations')
    op.drop_index(op.f('ix_prediction_feedback_harvest_actual_id'), table_name='prediction_feedback')
    op.drop_table('prediction_feedback')
    op.drop_index(op.f('ix_inventory_lots_owner_id'), table_name='inventory_lots')
    op.drop_table('inventory_lots')
    op.drop_index(op.f('ix_yield_predictions_crop_cycle_id'), table_name='yield_predictions')
    op.drop_table('yield_predictions')
    op.drop_table('harvest_actuals')
    op.drop_index(op.f('ix_calibration_profiles_crop_id'), table_name='calibration_profiles')
    op.drop_table('calibration_profiles')
    op.drop_table('weather_daily')
