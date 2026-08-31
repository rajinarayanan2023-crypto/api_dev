"""add audit columns (created_at/updated_at/created_by/updated_by)

Revision ID: 70a270f302c0
Revises: 152b75a239f1
Create Date: 2026-08-30 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '70a270f302c0'
down_revision = '152b75a239f1'
branch_labels = None
depends_on = None

# Top-level entities only (per product decision) — child/detail tables
# (Employee_Salary_History, Employee_Credits, Expense_Items, Fuel_Readings,
# Fuel_Entry_Oil_Rows, Payment_Lines, Fuel_Entry_Bills, Credit_Customer_Bills,
# Credit_Ledger_Entries, Lubricant_Price_History, Lubricant_Purchase_History,
# Offer_Send_Recipients) inherit accountability from their parent row and are
# intentionally left alone, as is Refresh_Tokens (a security/session table,
# not a business record).
#
# Attendance_Records gets its DB columns here too (so this migration is the
# only place a new head has to reconcile against), but its ORM model,
# schema, service, and controller are intentionally NOT touched in this
# change — owned by a parallel session doing the Attendance/Employee work.
_ALREADY_HAS_CREATED_AT = {
    'Employees', 'Lubricant_Products', 'Credit_Customers',
    'Commission_Rate_History', 'Fuel_Entries', 'Stations', 'Users',
}
_ALREADY_HAS_UPDATED_AT = {'Fuel_Entries', 'Stations'}

_ALL_TABLES = [
    'Employees',
    'Lubricant_Products',
    'Expense_Days',
    'Attendance_Records',
    'Credit_Customers',
    'Commission_Rate_History',
    'Offer_Sends',
    'Fuel_Entries',
    'Stations',
    'Users',
]

# Backfill target for existing rows with no acting-user concept — the one
# real admin account in the DB at the time this migration was written. New
# rows going forward get the real acting user from the service layer;
# existing rows would otherwise be left with an untraceable NULL author.
_BACKFILL_EMAIL = 'naveenbharath2747@gmail.com'


def upgrade() -> None:
    for table in _ALL_TABLES:
        if table not in _ALREADY_HAS_CREATED_AT:
            op.add_column(
                table,
                sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            )
        if table not in _ALREADY_HAS_UPDATED_AT:
            op.add_column(
                table,
                sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            )
        op.add_column(table, sa.Column('created_by', sa.UUID(), nullable=True))
        op.add_column(table, sa.Column('updated_by', sa.UUID(), nullable=True))

        table_slug = table.lower()
        op.create_foreign_key(
            f'fk_{table_slug}_created_by_users', table, 'Users', ['created_by'], ['id'], ondelete='SET NULL'
        )
        op.create_foreign_key(
            f'fk_{table_slug}_updated_by_users', table, 'Users', ['updated_by'], ['id'], ondelete='SET NULL'
        )

    # Backfill existing rows to the one real admin account, if it exists yet
    # (a brand-new install has no data to backfill and may not have created
    # this account at all — in that case there's nothing to do).
    conn = op.get_bind()
    admin_row = conn.execute(
        sa.text('SELECT id FROM "Users" WHERE email = :email'), {'email': _BACKFILL_EMAIL}
    ).fetchone()
    if admin_row is not None:
        admin_id = admin_row[0]
        for table in _ALL_TABLES:
            conn.execute(
                sa.text(f'UPDATE "{table}" SET created_by = :uid, updated_by = :uid WHERE created_by IS NULL'),
                {'uid': admin_id},
            )


def downgrade() -> None:
    for table in reversed(_ALL_TABLES):
        table_slug = table.lower()
        op.drop_constraint(f'fk_{table_slug}_updated_by_users', table, type_='foreignkey')
        op.drop_constraint(f'fk_{table_slug}_created_by_users', table, type_='foreignkey')
        op.drop_column(table, 'updated_by')
        op.drop_column(table, 'created_by')
        if table not in _ALREADY_HAS_UPDATED_AT:
            op.drop_column(table, 'updated_at')
        if table not in _ALREADY_HAS_CREATED_AT:
            op.drop_column(table, 'created_at')
