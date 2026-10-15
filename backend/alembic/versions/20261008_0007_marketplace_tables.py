"""marketplace

Revision ID: 0007_marketplace

Phase 6: orders, farmer participation, collection hubs, produce batches, quality checks, reminders,
notifications, crop-health analyses; pool closure and declined-lot exclusion.
Revises: 0006_pooling
Create Date: 2026-10-08 03:46:19.769341
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0007_marketplace'
down_revision: str | None = '0006_pooling'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('collection_hubs',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('district', sa.String(length=100), nullable=True),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(latitude IS NULL) = (longitude IS NULL)', name=op.f('ck_collection_hubs_coordinates_paired')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_hubs')),
    sa.UniqueConstraint('name', name='uq_collection_hubs_name')
    )
    op.create_table('notifications',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.Enum('reminder', 'participation_request', 'participation_response', 'shortage', 'reallocation', 'order_update', 'collection', 'quality', 'fulfilment', 'buyer_opportunity', name='notification_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('dedup_key', sa.String(length=160), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    sa.UniqueConstraint('user_id', 'dedup_key', name='uq_notifications_user_id_dedup_key')
    )
    op.create_index('ix_notifications_user_id_created_at', 'notifications', ['user_id', 'created_at'], unique=False)
    op.create_table('buyer_orders',
    sa.Column('buyer_id', sa.Uuid(), nullable=False),
    sa.Column('pool_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('placed', 'confirmed', 'in_fulfilment', 'fulfilled', 'partially_fulfilled', 'cancelled', name='order_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('ordered_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('fulfilled_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('delivery_hub_id', sa.Uuid(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=80), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('fulfilled_kg >= 0 AND fulfilled_kg <= ordered_kg', name=op.f('ck_buyer_orders_fulfilled_within_order')),
    sa.CheckConstraint('ordered_kg > 0', name=op.f('ck_buyer_orders_ordered_positive')),
    sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], name=op.f('fk_buyer_orders_buyer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['delivery_hub_id'], ['collection_hubs.id'], name=op.f('fk_buyer_orders_delivery_hub_id_collection_hubs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['pool_id'], ['harvest_pools.id'], name=op.f('fk_buyer_orders_pool_id_harvest_pools'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buyer_orders')),
    sa.UniqueConstraint('buyer_id', 'idempotency_key', name='uq_buyer_orders_buyer_id_idempotency_key'),
    sa.UniqueConstraint('pool_id', name='uq_buyer_orders_pool_id')
    )
    op.create_index(op.f('ix_buyer_orders_buyer_id'), 'buyer_orders', ['buyer_id'], unique=False)
    op.create_table('crop_health_analyses',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=True),
    sa.Column('image_sha256', sa.String(length=64), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('label', sa.Enum('healthy', 'possible_disease', 'stress', 'possible_deficiency', 'unknown', name='crop_health_class', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('probabilities', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('features', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('model_name', sa.String(length=40), nullable=False),
    sa.Column('model_version', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('width > 0 AND height > 0', name=op.f('ck_crop_health_analyses_dimensions_positive')),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_crop_health_analyses_crop_cycle_id_crop_cycles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_crop_health_analyses_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crop_health_analyses'))
    )
    op.create_index(op.f('ix_crop_health_analyses_owner_id'), 'crop_health_analyses', ['owner_id'], unique=False)
    op.create_table('reminders',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('reminder_type', sa.Enum('crop_observation', 'irrigation', 'activity', 'crop_health', 'harvest', 'buyer_opportunity', 'collection', 'expense', 'custom', name='reminder_type', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recurrence', sa.Enum('none', 'daily', 'weekly', name='recurrence', native_enum=False, create_constraint=True, length=8), nullable=False),
    sa.Column('status', sa.Enum('pending', 'done', 'dismissed', name='reminder_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('farm_id', sa.Uuid(), nullable=True),
    sa.Column('crop_cycle_id', sa.Uuid(), nullable=True),
    sa.Column('source', sa.String(length=24), nullable=False),
    sa.Column('notified_for', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['crop_cycle_id'], ['crop_cycles.id'], name=op.f('fk_reminders_crop_cycle_id_crop_cycles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], name=op.f('fk_reminders_farm_id_farms'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_reminders_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reminders'))
    )
    op.create_index('ix_reminders_owner_id_status_due_at', 'reminders', ['owner_id', 'status', 'due_at'], unique=False)
    op.create_table('farmer_participations',
    sa.Column('allocation_id', sa.Uuid(), nullable=False),
    sa.Column('farmer_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'accepted', 'declined', 'withdrawn', name='participation_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['allocation_id'], ['harvest_allocations.id'], name=op.f('fk_farmer_participations_allocation_id_harvest_allocations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['farmer_id'], ['users.id'], name=op.f('fk_farmer_participations_farmer_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_farmer_participations')),
    sa.UniqueConstraint('allocation_id', name='uq_farmer_participations_allocation_id')
    )
    op.create_index(op.f('ix_farmer_participations_farmer_id'), 'farmer_participations', ['farmer_id'], unique=False)
    op.create_table('buyer_order_items',
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('allocation_id', sa.Uuid(), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('farmer_id', sa.Uuid(), nullable=False),
    sa.Column('participation_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('fulfilled_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('status', sa.Enum('awaiting_farmer', 'accepted', 'declined', 'removed', 'fulfilled', 'short', 'cancelled', name='order_item_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('fulfilled_kg <= quantity_kg', name=op.f('ck_buyer_order_items_fulfilled_within_item')),
    sa.CheckConstraint('quantity_kg >= 0 AND fulfilled_kg >= 0', name=op.f('ck_buyer_order_items_quantities_non_negative')),
    sa.ForeignKeyConstraint(['allocation_id'], ['harvest_allocations.id'], name=op.f('fk_buyer_order_items_allocation_id_harvest_allocations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['farmer_id'], ['users.id'], name=op.f('fk_buyer_order_items_farmer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], name=op.f('fk_buyer_order_items_lot_id_inventory_lots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['buyer_orders.id'], name=op.f('fk_buyer_order_items_order_id_buyer_orders'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['participation_id'], ['farmer_participations.id'], name=op.f('fk_buyer_order_items_participation_id_farmer_participations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buyer_order_items')),
    sa.UniqueConstraint('allocation_id', name='uq_buyer_order_items_allocation_id')
    )
    op.create_index(op.f('ix_buyer_order_items_farmer_id'), 'buyer_order_items', ['farmer_id'], unique=False)
    op.create_index(op.f('ix_buyer_order_items_lot_id'), 'buyer_order_items', ['lot_id'], unique=False)
    op.create_index(op.f('ix_buyer_order_items_order_id'), 'buyer_order_items', ['order_id'], unique=False)
    op.create_table('produce_batches',
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('order_item_id', sa.Uuid(), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('harvest_actual_id', sa.Uuid(), nullable=False),
    sa.Column('hub_id', sa.Uuid(), nullable=False),
    sa.Column('received_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_by', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('received', 'quality_checked', 'closed', name='batch_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('received_kg > 0', name=op.f('ck_produce_batches_received_positive')),
    sa.ForeignKeyConstraint(['harvest_actual_id'], ['harvest_actuals.id'], name=op.f('fk_produce_batches_harvest_actual_id_harvest_actuals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['hub_id'], ['collection_hubs.id'], name=op.f('fk_produce_batches_hub_id_collection_hubs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], name=op.f('fk_produce_batches_lot_id_inventory_lots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_item_id'], ['buyer_order_items.id'], name=op.f('fk_produce_batches_order_item_id_buyer_order_items'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['received_by'], ['users.id'], name=op.f('fk_produce_batches_received_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_produce_batches')),
    sa.UniqueConstraint('code', name='uq_produce_batches_code')
    )
    op.create_index(op.f('ix_produce_batches_hub_id'), 'produce_batches', ['hub_id'], unique=False)
    op.create_index('ix_produce_batches_order_item_id', 'produce_batches', ['order_item_id'], unique=False)
    op.create_table('quality_checks',
    sa.Column('batch_id', sa.Uuid(), nullable=False),
    sa.Column('inspector_id', sa.Uuid(), nullable=False),
    sa.Column('grade', sa.Enum('A', 'B', 'C', name='quality_grade', native_enum=False, create_constraint=True, length=2), nullable=True),
    sa.Column('result', sa.Enum('accepted', 'partially_accepted', 'rejected', name='quality_result', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('accepted_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('rejected_kg', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('moisture_percent', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('defects', sa.Text(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("(result = 'accepted' AND rejected_kg = 0 AND accepted_kg > 0) OR (result = 'rejected' AND accepted_kg = 0) OR (result = 'partially_accepted' AND accepted_kg > 0 AND rejected_kg > 0)", name=op.f('ck_quality_checks_result_matches_quantities')),
    sa.CheckConstraint('accepted_kg >= 0 AND rejected_kg >= 0', name=op.f('ck_quality_checks_quantities_non_negative')),
    sa.CheckConstraint('moisture_percent IS NULL OR (moisture_percent >= 0 AND moisture_percent <= 100)', name=op.f('ck_quality_checks_moisture_range')),
    sa.ForeignKeyConstraint(['batch_id'], ['produce_batches.id'], name=op.f('fk_quality_checks_batch_id_produce_batches'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['inspector_id'], ['users.id'], name=op.f('fk_quality_checks_inspector_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quality_checks')),
    sa.UniqueConstraint('batch_id', name='uq_quality_checks_batch_id')
    )
    op.add_column('harvest_pool_members', sa.Column('excluded', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('harvest_pools', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('harvest_pools', sa.Column('close_reason', sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column('harvest_pools', 'close_reason')
    op.drop_column('harvest_pools', 'closed_at')
    op.drop_column('harvest_pool_members', 'excluded')
    op.drop_table('quality_checks')
    op.drop_index('ix_produce_batches_order_item_id', table_name='produce_batches')
    op.drop_index(op.f('ix_produce_batches_hub_id'), table_name='produce_batches')
    op.drop_table('produce_batches')
    op.drop_index(op.f('ix_buyer_order_items_order_id'), table_name='buyer_order_items')
    op.drop_index(op.f('ix_buyer_order_items_lot_id'), table_name='buyer_order_items')
    op.drop_index(op.f('ix_buyer_order_items_farmer_id'), table_name='buyer_order_items')
    op.drop_table('buyer_order_items')
    op.drop_index(op.f('ix_farmer_participations_farmer_id'), table_name='farmer_participations')
    op.drop_table('farmer_participations')
    op.drop_index('ix_reminders_owner_id_status_due_at', table_name='reminders')
    op.drop_table('reminders')
    op.drop_index(op.f('ix_crop_health_analyses_owner_id'), table_name='crop_health_analyses')
    op.drop_table('crop_health_analyses')
    op.drop_index(op.f('ix_buyer_orders_buyer_id'), table_name='buyer_orders')
    op.drop_table('buyer_orders')
    op.drop_index('ix_notifications_user_id_created_at', table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('collection_hubs')
