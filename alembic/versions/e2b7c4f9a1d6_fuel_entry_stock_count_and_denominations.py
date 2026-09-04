"""fuel entry oil-row stock_count numeric + payment line denominations

Revision ID: e2b7c4f9a1d6
Revises: f3e7a9c1b5d8
Create Date: 2026-09-03 00:00:00.000000

Two independent fixes bundled together since both touch Fuel Entry's write
path and neither is large enough to earn its own migration:

1. Fuel_Entry_Oil_Rows.stock_count was Integer, but FuelEntryOilRowIn (the
   write schema) already accepted a 3-decimal number, and the UI clamps
   counts against a stock figure rounded to 3 decimals — a fractional count
   passed validation and then got silently truncated at the database.
2. Payment_Lines.denominations (new, nullable JSONB) — the till-count
   breakdown (₹500 x n, ₹200 x n, ... + coins) behind a cash line's amount
   had nowhere to persist; only the derived total survived a save.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e2b7c4f9a1d6'
down_revision = 'f3e7a9c1b5d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'Fuel_Entry_Oil_Rows',
        'stock_count',
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 3),
        postgresql_using='stock_count::numeric(10,3)',
        server_default=sa.text('0'),
    )
    op.add_column('Payment_Lines', sa.Column('denominations', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('Payment_Lines', 'denominations')
    op.alter_column(
        'Fuel_Entry_Oil_Rows',
        'stock_count',
        existing_type=sa.Numeric(10, 3),
        type_=sa.Integer(),
        postgresql_using='round(stock_count)::integer',
        server_default=sa.text('0'),
    )
