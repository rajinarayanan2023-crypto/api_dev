"""add wa_message_id and delivered/read statuses to Offer_Send_Recipients

Revision ID: a8f3d2c7e916
Revises: 5a2c9bd0c4fa
Create Date: 2026-10-06 00:00:00.000000

Meta's webhook delivery-status events (whatsapp_webhook_controller.py) are
keyed by its own message id, which was never persisted anywhere — a send
could only ever show "sent" (accepted by Meta), never whether it actually
reached/was read on the customer's phone, or bounced after acceptance.
wa_message_id is what a webhook event gets matched back to this specific
row by (see OfferService.update_delivery_status); the status CHECK is
widened to allow the two new real outcomes that match can write.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a8f3d2c7e916'
down_revision = '5a2c9bd0c4fa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('Offer_Send_Recipients', sa.Column('wa_message_id', sa.Text(), nullable=True))
    op.create_index(
        'idx_offer_send_recipients_wa_message_id', 'Offer_Send_Recipients', ['wa_message_id'], unique=True
    )
    op.drop_constraint('ck_offer_send_recipients_status', 'Offer_Send_Recipients', type_='check')
    op.create_check_constraint(
        'ck_offer_send_recipients_status',
        'Offer_Send_Recipients',
        "status IN ('pending', 'sent', 'delivered', 'read', 'failed', 'blocked')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_offer_send_recipients_status', 'Offer_Send_Recipients', type_='check')
    op.create_check_constraint(
        'ck_offer_send_recipients_status',
        'Offer_Send_Recipients',
        "status IN ('pending', 'sent', 'failed', 'blocked')",
    )
    op.drop_index('idx_offer_send_recipients_wa_message_id', table_name='Offer_Send_Recipients')
    op.drop_column('Offer_Send_Recipients', 'wa_message_id')
