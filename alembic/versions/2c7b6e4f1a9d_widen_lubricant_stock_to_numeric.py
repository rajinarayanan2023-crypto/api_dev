"""widen Lubricant_Products.stock from Integer to Numeric

Revision ID: 2c7b6e4f1a9d
Revises: 8f3c1a9d5e2b
Create Date: 2026-08-30 23:25:00.000000

Pump 2's nozzle-dispensed oil is measured in fractional litres and gets
attributed to a linked Lubricant product's stock when a Fuel Entry
finalizes — an Integer column would truncate or reject that. Purchase qty
and opening_stock stay Integer (real restocks are always whole units);
only the running stock balance itself needs to hold a fraction.
"""
from alembic import op
import sqlalchemy as sa


revision = '2c7b6e4f1a9d'
down_revision = '8f3c1a9d5e2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'Lubricant_Products',
        'stock',
        type_=sa.Numeric(12, 3),
        postgresql_using='stock::numeric(12,3)',
        existing_server_default=sa.text('0'),
    )


def downgrade() -> None:
    op.alter_column(
        'Lubricant_Products',
        'stock',
        type_=sa.Integer(),
        postgresql_using='round(stock)::integer',
        existing_server_default=sa.text('0'),
    )
