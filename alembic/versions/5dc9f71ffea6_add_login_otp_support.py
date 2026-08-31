"""add login otp support

Revision ID: 5dc9f71ffea6
Revises: 2c7b6e4f1a9d
Create Date: 2026-08-30 23:36:28.274775

Adds Users.phone (where login OTPs are sent) and the Login_Otps table
(hashed code + expiry + attempt count for the new OTP-verification step in
/auth/login). Autogenerate also proposed dropping Attendance_Records'
audit columns — that's model/DB drift unrelated to this change (owned by
the audit-columns migration), stripped out here so this migration only
does what its message says.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5dc9f71ffea6'
down_revision = '2c7b6e4f1a9d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('Users', sa.Column('phone', sa.Text(), nullable=True))
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


def downgrade() -> None:
    op.drop_index(op.f('ix_Login_Otps_user_id'), table_name='Login_Otps')
    op.drop_table('Login_Otps')
    op.drop_column('Users', 'phone')
