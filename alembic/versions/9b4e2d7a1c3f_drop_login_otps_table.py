"""drop login_otps table

Revision ID: 9b4e2d7a1c3f
Revises: 255e6cf2d92c
Create Date: 2026-09-01 00:00:00.000000

Login OTPs are no longer persisted (see app/core/otp_store.py — the
5-minute-lived code now lives purely in memory, per user_id), so the
Login_Otps table this app wrote to is dropped here. Users.phone is left in
place — it's still where the OTP SMS is sent, unrelated to how/where the
code itself is stored.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9b4e2d7a1c3f'
down_revision = '255e6cf2d92c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f('ix_Login_Otps_user_id'), table_name='Login_Otps')
    op.drop_table('Login_Otps')


def downgrade() -> None:
    op.create_table('Login_Otps',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['Users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_Login_Otps_user_id'), 'Login_Otps', ['user_id'], unique=False)
