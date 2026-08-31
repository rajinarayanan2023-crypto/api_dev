"""allow 'expense' as a Payment_Lines type

Revision ID: 8f3c1a9d5e2b
Revises: 70a270f302c0
Create Date: 2026-08-30 23:10:00.000000

The Fuel Entry UI lets a shift record an "expense" payment line (cash
collected but spent straight back out on-site) alongside cash/credit/
employee_credit — reconciliation-only, no downstream ledger/stock effect,
but it still needs to be a storable line type.
"""
from alembic import op


revision = '8f3c1a9d5e2b'
down_revision = '70a270f302c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_payment_lines_type', 'Payment_Lines', type_='check')
    op.create_check_constraint(
        'ck_payment_lines_type',
        'Payment_Lines',
        "type IN ('cash', 'credit', 'employee_credit', 'expense')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_payment_lines_type', 'Payment_Lines', type_='check')
    op.create_check_constraint(
        'ck_payment_lines_type',
        'Payment_Lines',
        "type IN ('cash', 'credit', 'employee_credit')",
    )
