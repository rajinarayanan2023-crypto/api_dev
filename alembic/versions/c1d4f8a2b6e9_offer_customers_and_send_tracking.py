"""offer customers and real send tracking

Revision ID: c1d4f8a2b6e9
Revises: 7a1f9c4e6b2d
Create Date: 2026-09-03 00:00:00.000000

Offers gets its own standalone recipient list (offer_customers) instead of
reusing Credit_Customers, and Offer_Send_Recipients gains real per-recipient
delivery tracking (status/provider_response/sent_at) instead of just
recording that a customer was included in the send.

Offer_Sends and Offer_Send_Recipients already existed (see
152b75a239f1_initial_schema and 70a270f302c0_add_audit_columns) — this
migration ALTERs them, it does not recreate them:
  - Offer_Sends: + template_used
  - Offer_Send_Recipients: + status, provider_response, sent_at, created_at;
    customer_id renamed to offer_customer_id and repointed from
    Credit_Customers to the new offer_customers table.

Both tables were empty in every environment this was written against, so
there's no data to backfill across the FK repoint.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c1d4f8a2b6e9'
down_revision = '7a1f9c4e6b2d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'offer_customers',
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('phone', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('Offer_Sends', sa.Column('template_used', sa.Text(), nullable=True))

    op.add_column(
        'Offer_Send_Recipients',
        sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    )
    op.add_column('Offer_Send_Recipients', sa.Column('provider_response', sa.Text(), nullable=True))
    op.add_column('Offer_Send_Recipients', sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'Offer_Send_Recipients',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_check_constraint(
        'ck_offer_send_recipients_status',
        'Offer_Send_Recipients',
        "status IN ('pending', 'sent', 'failed', 'blocked')",
    )

    op.drop_constraint('Offer_Send_Recipients_customer_id_fkey', 'Offer_Send_Recipients', type_='foreignkey')
    op.alter_column('Offer_Send_Recipients', 'customer_id', new_column_name='offer_customer_id')
    op.create_foreign_key(
        'Offer_Send_Recipients_offer_customer_id_fkey',
        'Offer_Send_Recipients',
        'offer_customers',
        ['offer_customer_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('Offer_Send_Recipients_offer_customer_id_fkey', 'Offer_Send_Recipients', type_='foreignkey')
    op.alter_column('Offer_Send_Recipients', 'offer_customer_id', new_column_name='customer_id')
    op.create_foreign_key(
        'Offer_Send_Recipients_customer_id_fkey',
        'Offer_Send_Recipients',
        'Credit_Customers',
        ['customer_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.drop_constraint('ck_offer_send_recipients_status', 'Offer_Send_Recipients', type_='check')
    op.drop_column('Offer_Send_Recipients', 'created_at')
    op.drop_column('Offer_Send_Recipients', 'sent_at')
    op.drop_column('Offer_Send_Recipients', 'provider_response')
    op.drop_column('Offer_Send_Recipients', 'status')

    op.drop_column('Offer_Sends', 'template_used')

    op.drop_table('offer_customers')
