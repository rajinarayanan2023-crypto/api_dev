"""drop audit columns from users

Revision ID: 255e6cf2d92c
Revises: 5dc9f71ffea6
Create Date: 2026-09-01 14:25:24.290700

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '255e6cf2d92c'
down_revision = '5dc9f71ffea6'
branch_labels = None
depends_on = None


# Users is the one table with no audit trail (product decision) — every
# other table added by 70a270f302c0 keeps created_at/updated_at/created_by/
# updated_by. created_at on Users predates that migration (it was part of
# the initial schema); dropped here anyway per the same decision.


def upgrade() -> None:
    op.drop_constraint('fk_users_updated_by_users', 'Users', type_='foreignkey')
    op.drop_constraint('fk_users_created_by_users', 'Users', type_='foreignkey')
    op.drop_column('Users', 'updated_by')
    op.drop_column('Users', 'created_by')
    op.drop_column('Users', 'updated_at')
    op.drop_column('Users', 'created_at')


def downgrade() -> None:
    op.add_column('Users', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('Users', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('Users', sa.Column('created_by', sa.UUID(), nullable=True))
    op.add_column('Users', sa.Column('updated_by', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_users_created_by_users', 'Users', 'Users', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_users_updated_by_users', 'Users', 'Users', ['updated_by'], ['id'], ondelete='SET NULL')
