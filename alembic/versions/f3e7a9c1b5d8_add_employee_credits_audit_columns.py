"""add employee credits audit columns

Revision ID: f3e7a9c1b5d8
Revises: c1d4f8a2b6e9
Create Date: 2026-09-01 00:00:00.000000

Employee_Credits was deliberately left without its own audit trail in
70a270f302c0 (a child/detail table inheriting accountability from its
parent Employee row). It's now also directly created/edited/deleted from
its own standalone screen, not just written as a Fuel Entry side effect, so
it gets the same created_at/updated_at/created_by/updated_by every
top-level table already has. created_at already existed as a plain column
(same type/default AuditMixin uses) — untouched here.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f3e7a9c1b5d8'
down_revision = 'c1d4f8a2b6e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('Employee_Credits', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('Employee_Credits', sa.Column('created_by', sa.UUID(), nullable=True))
    op.add_column('Employee_Credits', sa.Column('updated_by', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_employee_credits_created_by_users', 'Employee_Credits', 'Users', ['created_by'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_employee_credits_updated_by_users', 'Employee_Credits', 'Users', ['updated_by'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_employee_credits_updated_by_users', 'Employee_Credits', type_='foreignkey')
    op.drop_constraint('fk_employee_credits_created_by_users', 'Employee_Credits', type_='foreignkey')
    op.drop_column('Employee_Credits', 'updated_by')
    op.drop_column('Employee_Credits', 'created_by')
    op.drop_column('Employee_Credits', 'updated_at')
