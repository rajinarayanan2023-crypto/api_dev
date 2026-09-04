"""add offer send channel

Revision ID: 7a1f9c4e6b2d
Revises: 9b4e2d7a1c3f
Create Date: 2026-09-01 00:00:00.000000

Adds Offer_Sends.channel ('sms' | 'whatsapp') so a send record captures how
the message actually went out — 'sms' is dispatched server-side via
core/sms.py, 'whatsapp' is opened client-side as a wa.me deep link (no
server-side send exists for it), but both are still logged the same way.
Existing rows default to 'sms', the only channel that existed before this.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7a1f9c4e6b2d'
down_revision = '9b4e2d7a1c3f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('Offer_Sends', sa.Column('channel', sa.Text(), server_default=sa.text("'sms'"), nullable=False))
    op.create_check_constraint(
        'ck_offer_sends_channel', 'Offer_Sends', "channel IN ('sms', 'whatsapp')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_offer_sends_channel', 'Offer_Sends', type_='check')
    op.drop_column('Offer_Sends', 'channel')
