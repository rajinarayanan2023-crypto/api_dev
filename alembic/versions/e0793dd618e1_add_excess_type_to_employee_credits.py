"""add excess type to employee credits

Revision ID: e0793dd618e1
Revises: 2b832a191dc5
Create Date: 2026-10-07 11:53:44.368941

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e0793dd618e1'
down_revision = '2b832a191dc5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Autogenerate doesn't detect CHECK constraint text changes — hand-written.
    op.drop_constraint("ck_employee_credits_type", "Employee_Credits", type_="check")
    op.create_check_constraint(
        "ck_employee_credits_type", "Employee_Credits", "type IN ('credit', 'repayment', 'excess')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_employee_credits_type", "Employee_Credits", type_="check")
    op.create_check_constraint(
        "ck_employee_credits_type", "Employee_Credits", "type IN ('credit', 'repayment')"
    )
