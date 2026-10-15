"""phone verification: one-time codes for registration and login

Revision ID: 0008_phone_verification
Revises: 0007_marketplace
Create Date: 2026-10-09 18:00:00

Additive only: existing users keep working. Their phone_verified_at stays NULL (they were never verified) and their
next login's one-time code verifies them; registration_pending defaults to false so no existing account is affected.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0008_phone_verification'
down_revision: str | None = '0007_marketplace'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('phone_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('registration_pending', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_table('otp_challenges',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('purpose', sa.Enum('register', 'login', name='otp_purpose', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('decoy', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('sends', sa.Integer(), server_default='1', nullable=False),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('client', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_otp_challenges_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_otp_challenges'))
    )
    op.create_index('ix_otp_challenges_client_created_at', 'otp_challenges', ['client', 'created_at'], unique=False)
    op.create_index('ix_otp_challenges_phone_created_at', 'otp_challenges', ['phone', 'created_at'], unique=False)
    op.create_index(op.f('ix_otp_challenges_user_id'), 'otp_challenges', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_otp_challenges_user_id'), table_name='otp_challenges')
    op.drop_index('ix_otp_challenges_phone_created_at', table_name='otp_challenges')
    op.drop_index('ix_otp_challenges_client_created_at', table_name='otp_challenges')
    op.drop_table('otp_challenges')
    op.drop_column('users', 'registration_pending')
    op.drop_column('users', 'phone_verified_at')
