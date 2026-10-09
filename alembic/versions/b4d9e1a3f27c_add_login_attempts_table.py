"""add Login_Attempts table

Revision ID: b4d9e1a3f27c
Revises: a8f3d2c7e916
Create Date: 2026-10-13 00:00:00.000000

No durable record of failed logins existed anywhere — only console logs,
if that. This table backs both the account-lockout check
(LoginAttemptService.check_lockout, keyed by identifier, not IP — closes
the gap where slowapi's per-IP rate limiting can't catch many different
IPs each guessing the same account) and the new admin-only Login Attempts
screen.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b4d9e1a3f27c'
down_revision = 'a8f3d2c7e916'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'Login_Attempts',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('identifier', sa.Text(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['Users.id'], ondelete='SET NULL'),
    )
    op.create_check_constraint(
        'ck_login_attempts_action', 'Login_Attempts', "action IN ('login', 'verify_otp', 'change_password')"
    )
    op.create_index(
        'idx_login_attempts_identifier_action_created', 'Login_Attempts', ['identifier', 'action', 'created_at']
    )
    op.create_index('idx_login_attempts_created', 'Login_Attempts', ['created_at'])


def downgrade() -> None:
    op.drop_index('idx_login_attempts_created', table_name='Login_Attempts')
    op.drop_index('idx_login_attempts_identifier_action_created', table_name='Login_Attempts')
    op.drop_table('Login_Attempts')
