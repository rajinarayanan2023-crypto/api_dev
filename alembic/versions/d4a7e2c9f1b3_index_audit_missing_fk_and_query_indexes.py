"""index audit: missing FK and query-pattern indexes

Revision ID: d4a7e2c9f1b3
Revises: e2b7c4f9a1d6
Create Date: 2026-09-04 00:00:00.000000

One-time index audit across every table (Attendance_Records had already
been checked in an earlier diagnostic — this covers everything else, plus
one additional gap found on Attendance_Records itself). Every index below
is backed by an actual query in the codebase, not a speculative guess:

  - Credit_Ledger_Entries.source_fuel_entry_id (FK, unindexed): filtered
    directly in FuelEntryService._remove_credit_ledger_by_source — runs on
    every edit/delete of an already-final fuel entry, to reverse that
    entry's credit-ledger side effect. Not covered by the existing
    idx_credit_ledger_entries_customer (customer_id, date) composite —
    source_fuel_entry_id isn't a prefix of it.

  - Employee_Credits.source_fuel_entry_id (FK, unindexed): same pattern,
    filtered in FuelEntryService._remove_employee_credit_by_source. Not
    covered by idx_employee_credits_employee (employee_id, date).

  - Attendance_Records.date (single-column, currently only covered
    employee+date together): AttendanceRepository.list_for_range scans
    every employee's attendance for a whole month with no employee_id
    filter at all (the "list all attendance for a month" view) — the
    existing idx_attendance_employee_date/uq_attendance_records_employee_date
    composites both lead with employee_id, so neither helps a pure
    date-range scan.

  - Fuel_Entries(employee_id, date) composite: FuelEntryRepository.
    count_final_for_employee_on_date filters both together (the
    attendance auto-mark cascade, run on every finalized fuel entry).
    The existing idx_fuel_entries_employee (employee_id alone) still
    exists after this and isn't dropped here — narrowing scope stayed
    "add what's missing," not "reshape what's already there" — but it
    is now largely superseded by this composite via the leftmost-prefix
    rule; worth revisiting in a later cleanup pass.

Every other FK/date/status column called out in the audit request was
checked and found already covered (Fuel_Readings/Fuel_Entry_Oil_Rows/
Payment_Lines/Fuel_Entry_Bills/Offer_Send_Recipients all index their FKs
already; Commission_Rate_History.effective_from and Expense_Days.date are
each already unique-indexed; Refresh_Tokens.user_id is already indexed and
.expires_at is never used in a WHERE clause anywhere, only checked in
Python against an already-fetched row) — nothing speculative added for
those, per the "no query evidence, no index" rule this audit was run under.

CREATE INDEX CONCURRENTLY can't run inside a transaction block, and
env.py wraps the whole migration run in one — each index below is built
inside its own autocommit_block() to escape that, same as running each
statement in its own outside-of-transaction session.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4a7e2c9f1b3'
down_revision = 'e2b7c4f9a1d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_credit_ledger_entries_source_fuel_entry',
            'Credit_Ledger_Entries',
            ['source_fuel_entry_id'],
            unique=False,
            postgresql_concurrently=True,
        )
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_employee_credits_source_fuel_entry',
            'Employee_Credits',
            ['source_fuel_entry_id'],
            unique=False,
            postgresql_concurrently=True,
        )
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_attendance_date',
            'Attendance_Records',
            ['date'],
            unique=False,
            postgresql_concurrently=True,
        )
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_fuel_entries_employee_date',
            'Fuel_Entries',
            ['employee_id', 'date'],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index('idx_fuel_entries_employee_date', table_name='Fuel_Entries', postgresql_concurrently=True)
    with op.get_context().autocommit_block():
        op.drop_index('idx_attendance_date', table_name='Attendance_Records', postgresql_concurrently=True)
    with op.get_context().autocommit_block():
        op.drop_index('idx_employee_credits_source_fuel_entry', table_name='Employee_Credits', postgresql_concurrently=True)
    with op.get_context().autocommit_block():
        op.drop_index('idx_credit_ledger_entries_source_fuel_entry', table_name='Credit_Ledger_Entries', postgresql_concurrently=True)
