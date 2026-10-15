"""identity tables

Revision ID: 0002_identity
Revises: 0001_baseline
Create Date: 2026-10-07 07:58:24.128322
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0002_identity'
down_revision: str | None = '0001_baseline'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('login_attempts',
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('succeeded', sa.Boolean(), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts'))
    )
    op.create_index('ix_login_attempts_phone_attempted_at', 'login_attempts', ['phone', 'attempted_at'], unique=False)
    op.create_table('users',
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.Enum('farmer', 'buyer', 'admin', name='user_role', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('phone', name=op.f('uq_users_phone'))
    )
    op.create_table('buyer_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('business_name', sa.String(length=160), nullable=False),
    sa.Column('buyer_type', sa.Enum('retailer', 'wholesaler', 'processor', 'restaurant', 'other', name='buyer_type', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('district', sa.String(length=100), nullable=True),
    sa.Column('state', sa.String(length=100), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_buyer_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buyer_profiles')),
    sa.UniqueConstraint('user_id', name=op.f('uq_buyer_profiles_user_id'))
    )
    op.create_table('farmer_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('village', sa.String(length=100), nullable=True),
    sa.Column('district', sa.String(length=100), nullable=True),
    sa.Column('state', sa.String(length=100), nullable=True),
    sa.Column('preferred_language', sa.Enum('en', 'kn', name='preferred_language', native_enum=False, create_constraint=True, length=5), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_farmer_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_farmer_profiles')),
    sa.UniqueConstraint('user_id', name=op.f('uq_farmer_profiles_user_id'))
    )
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_table('farmer_profiles')
    op.drop_table('buyer_profiles')
    op.drop_table('users')
    op.drop_index('ix_login_attempts_phone_attempted_at', table_name='login_attempts')
    op.drop_table('login_attempts')
