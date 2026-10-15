"""pooling

Revision ID: 0006_pooling
Revises: 0005_intelligence
Create Date: 2026-10-07 17:29:01.056228
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0006_pooling'
down_revision: str | None = '0005_intelligence'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('buyer_demands',
    sa.Column('buyer_id', sa.Uuid(), nullable=False),
    sa.Column('crop_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('min_grade', sa.Enum('A', 'B', 'C', name='min_grade', native_enum=False, create_constraint=True, length=2), nullable=False),
    sa.Column('window_start', sa.Date(), nullable=False),
    sa.Column('window_end', sa.Date(), nullable=False),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('max_distance_km', sa.Numeric(precision=8, scale=1), nullable=True),
    sa.Column('min_confidence', sa.Numeric(precision=4, scale=1), nullable=False),
    sa.Column('max_risk', sa.Numeric(precision=4, scale=1), nullable=False),
    sa.Column('status', sa.Enum('open', 'pooled', 'cancelled', name='demand_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(latitude IS NULL) = (longitude IS NULL)', name=op.f('ck_buyer_demands_coordinates_paired')),
    sa.CheckConstraint('max_distance_km IS NULL OR max_distance_km > 0', name=op.f('ck_buyer_demands_distance_positive')),
    sa.CheckConstraint('min_confidence BETWEEN 0 AND 100 AND max_risk BETWEEN 0 AND 100', name=op.f('ck_buyer_demands_thresholds_range')),
    sa.CheckConstraint('quantity_kg > 0', name=op.f('ck_buyer_demands_quantity_positive')),
    sa.CheckConstraint('window_end >= window_start', name=op.f('ck_buyer_demands_window_ordered')),
    sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], name=op.f('fk_buyer_demands_buyer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['crop_id'], ['crops.id'], name=op.f('fk_buyer_demands_crop_id_crops'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buyer_demands'))
    )
    op.create_index(op.f('ix_buyer_demands_buyer_id'), 'buyer_demands', ['buyer_id'], unique=False)
    op.create_index(op.f('ix_buyer_demands_crop_id'), 'buyer_demands', ['crop_id'], unique=False)
    op.create_table('harvest_pools',
    sa.Column('demand_id', sa.Uuid(), nullable=False),
    sa.Column('buyer_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('filled', 'partial', 'at_risk', 'unfilled', name='pool_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('algorithm', sa.Enum('lp', 'greedy', name='pool_algorithm', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('demand_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('allocated_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('shortage_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('max_pool_risk', sa.Numeric(precision=4, scale=1), nullable=False),
    sa.Column('max_share', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('weights', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=80), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('allocated_kg >= 0 AND allocated_kg <= demand_kg', name=op.f('ck_harvest_pools_allocated_within_demand')),
    sa.CheckConstraint('shortage_kg >= 0', name=op.f('ck_harvest_pools_shortage_non_negative')),
    sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], name=op.f('fk_harvest_pools_buyer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['demand_id'], ['buyer_demands.id'], name=op.f('fk_harvest_pools_demand_id_buyer_demands'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_harvest_pools')),
    sa.UniqueConstraint('buyer_id', 'idempotency_key', name='uq_harvest_pools_buyer_id_idempotency_key'),
    sa.UniqueConstraint('demand_id', name='uq_harvest_pools_demand_id')
    )
    op.create_index(op.f('ix_harvest_pools_buyer_id'), 'harvest_pools', ['buyer_id'], unique=False)
    op.create_table('reallocation_events',
    sa.Column('pool_id', sa.Uuid(), nullable=False),
    sa.Column('trigger', sa.String(length=40), nullable=False),
    sa.Column('trigger_ref', sa.String(length=80), nullable=True),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('outcome', sa.Enum('no_change', 'full', 'partial', 'none', 'top_up', name='reallocation_outcome', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('algorithm', sa.String(length=16), nullable=False),
    sa.Column('shortage_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('replaced_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('unresolved_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('topped_up_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('steps', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('before', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('after', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('replaced_kg + unresolved_kg >= shortage_kg - 0.001', name=op.f('ck_reallocation_events_shortage_accounted')),
    sa.CheckConstraint('shortage_kg >= 0 AND replaced_kg >= 0 AND unresolved_kg >= 0', name=op.f('ck_reallocation_events_quantities_non_negative')),
    sa.ForeignKeyConstraint(['pool_id'], ['harvest_pools.id'], name=op.f('fk_reallocation_events_pool_id_harvest_pools'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reallocation_events')),
    sa.UniqueConstraint('idempotency_key', name='uq_reallocation_events_idempotency_key')
    )
    op.create_index(op.f('ix_reallocation_events_pool_id'), 'reallocation_events', ['pool_id'], unique=False)
    op.create_table('harvest_pool_members',
    sa.Column('pool_id', sa.Uuid(), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('components', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], name=op.f('fk_harvest_pool_members_lot_id_inventory_lots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['pool_id'], ['harvest_pools.id'], name=op.f('fk_harvest_pool_members_pool_id_harvest_pools'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_harvest_pool_members')),
    sa.UniqueConstraint('pool_id', 'lot_id', name='uq_harvest_pool_members_pool_id_lot_id')
    )
    op.create_index(op.f('ix_harvest_pool_members_lot_id'), 'harvest_pool_members', ['lot_id'], unique=False)
    op.create_index(op.f('ix_harvest_pool_members_pool_id'), 'harvest_pool_members', ['pool_id'], unique=False)
    op.create_table('harvest_allocations',
    sa.Column('pool_id', sa.Uuid(), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('member_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('status', sa.Enum('active', 'reduced', 'released', 'fulfilled', name='allocation_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('reservation_id', sa.Uuid(), nullable=True),
    sa.Column('reservation_seq', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity_kg >= 0', name=op.f('ck_harvest_allocations_quantity_non_negative')),
    sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], name=op.f('fk_harvest_allocations_lot_id_inventory_lots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['member_id'], ['harvest_pool_members.id'], name=op.f('fk_harvest_allocations_member_id_harvest_pool_members'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['pool_id'], ['harvest_pools.id'], name=op.f('fk_harvest_allocations_pool_id_harvest_pools'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reservation_id'], ['inventory_reservations.id'], name=op.f('fk_harvest_allocations_reservation_id_inventory_reservations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_harvest_allocations')),
    sa.UniqueConstraint('pool_id', 'lot_id', name='uq_harvest_allocations_pool_id_lot_id')
    )
    op.create_index(op.f('ix_harvest_allocations_lot_id'), 'harvest_allocations', ['lot_id'], unique=False)
    op.create_index(op.f('ix_harvest_allocations_pool_id'), 'harvest_allocations', ['pool_id'], unique=False)
    op.create_table('allocation_ledger',
    sa.Column('pool_id', sa.Uuid(), nullable=False),
    sa.Column('allocation_id', sa.Uuid(), nullable=True),
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('quantity_before', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('quantity_after', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('reallocation_event_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('quantity_before >= 0 AND quantity_after >= 0', name=op.f('ck_allocation_ledger_quantities_non_negative')),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_allocation_ledger_actor_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['allocation_id'], ['harvest_allocations.id'], name=op.f('fk_allocation_ledger_allocation_id_harvest_allocations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], name=op.f('fk_allocation_ledger_lot_id_inventory_lots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['pool_id'], ['harvest_pools.id'], name=op.f('fk_allocation_ledger_pool_id_harvest_pools'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reallocation_event_id'], ['reallocation_events.id'], name=op.f('fk_allocation_ledger_reallocation_event_id_reallocation_events'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_allocation_ledger'))
    )
    op.create_index(op.f('ix_allocation_ledger_pool_id'), 'allocation_ledger', ['pool_id'], unique=False)
    op.add_column('inventory_lots', sa.Column('pool_eligible', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('inventory_lots', sa.Column('expected_grade', sa.Enum('A', 'B', 'C', name='expected_grade', native_enum=False, create_constraint=True, length=2), server_default='B', nullable=False))


def downgrade() -> None:
    op.drop_column('inventory_lots', 'expected_grade')
    op.drop_column('inventory_lots', 'pool_eligible')
    op.drop_index(op.f('ix_allocation_ledger_pool_id'), table_name='allocation_ledger')
    op.drop_table('allocation_ledger')
    op.drop_index(op.f('ix_harvest_allocations_pool_id'), table_name='harvest_allocations')
    op.drop_index(op.f('ix_harvest_allocations_lot_id'), table_name='harvest_allocations')
    op.drop_table('harvest_allocations')
    op.drop_index(op.f('ix_harvest_pool_members_pool_id'), table_name='harvest_pool_members')
    op.drop_index(op.f('ix_harvest_pool_members_lot_id'), table_name='harvest_pool_members')
    op.drop_table('harvest_pool_members')
    op.drop_index(op.f('ix_reallocation_events_pool_id'), table_name='reallocation_events')
    op.drop_table('reallocation_events')
    op.drop_index(op.f('ix_harvest_pools_buyer_id'), table_name='harvest_pools')
    op.drop_table('harvest_pools')
    op.drop_index(op.f('ix_buyer_demands_crop_id'), table_name='buyer_demands')
    op.drop_index(op.f('ix_buyer_demands_buyer_id'), table_name='buyer_demands')
    op.drop_table('buyer_demands')
