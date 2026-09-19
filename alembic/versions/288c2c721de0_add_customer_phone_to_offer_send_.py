"""add customer_phone to offer send recipients

Revision ID: 288c2c721de0
Revises: c4d8f6b1e7a2
Create Date: 2026-09-18 18:10:53.568281

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '288c2c721de0'
down_revision = 'c4d8f6b1e7a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("Offer_Send_Recipients", sa.Column("customer_phone", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("Offer_Send_Recipients", "customer_phone")
