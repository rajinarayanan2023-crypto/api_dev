"""offer_send_recipients: drop FK to offer_customers, snapshot name

Revision ID: b3f7e5a2c9d4
Revises: d4a7e2c9f1b3
Create Date: 2026-09-12 00:00:00.000000

offer_customers now needs to be a genuinely standalone table — nothing else
in the schema references it, so deleting a customer (the Offers screen hard-
deletes now, see the earlier offer-customer-delete migration/change) can
never have any side effect on past send history. Previously,
Offer_Send_Recipients.offer_customer_id was an ON DELETE CASCADE FK, so
deleting a customer silently dropped their row out of every past send's
recipient list; customer_name itself was never stored, just resolved via a
live join at read time (see OfferService._attach_recipient_names, removed).

Offer_Sends and Offer_Send_Recipients were empty in every environment this
was written against (confirmed against production immediately before
writing this), so there is no data to snapshot/backfill across the change.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3f7e5a2c9d4'
down_revision = 'd4a7e2c9f1b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('Offer_Send_Recipients', sa.Column('customer_name', sa.Text(), nullable=False, server_default=''))
    op.alter_column('Offer_Send_Recipients', 'customer_name', server_default=None)

    op.drop_constraint('Offer_Send_Recipients_offer_customer_id_fkey', 'Offer_Send_Recipients', type_='foreignkey')
    op.drop_constraint('uq_offer_send_recipients_send_customer', 'Offer_Send_Recipients', type_='unique')
    op.drop_index('idx_offer_send_recipients_customer', table_name='Offer_Send_Recipients')
    op.drop_column('Offer_Send_Recipients', 'offer_customer_id')


def downgrade() -> None:
    # Lossy: there's no customer id to restore from a name snapshot alone,
    # so this comes back nullable rather than the original NOT NULL.
    op.add_column('Offer_Send_Recipients', sa.Column('offer_customer_id', sa.UUID(), nullable=True))
    op.create_index('idx_offer_send_recipients_customer', 'Offer_Send_Recipients', ['offer_customer_id'])
    op.create_unique_constraint(
        'uq_offer_send_recipients_send_customer', 'Offer_Send_Recipients', ['offer_send_id', 'offer_customer_id']
    )
    op.create_foreign_key(
        'Offer_Send_Recipients_offer_customer_id_fkey',
        'Offer_Send_Recipients',
        'offer_customers',
        ['offer_customer_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.drop_column('Offer_Send_Recipients', 'customer_name')
