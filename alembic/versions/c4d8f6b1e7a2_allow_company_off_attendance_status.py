"""allow 'company_off' as an Attendance_Records status

Revision ID: c4d8f6b1e7a2
Revises: b3f7e5a2c9d4
Create Date: 2026-09-13 00:00:00.000000

A company-declared off day (holiday/closure) — unlike duty_off, this one
counts as a paid day worked (see shiftUnits in ui/src/utils/attendance.js)
and is never treated as an absence/leave (see FuelEntryForm's
unavailableEmployeeIds), so the employee still shows as assignable to a
shift on it.
"""
from alembic import op


revision = 'c4d8f6b1e7a2'
down_revision = 'b3f7e5a2c9d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_attendance_records_status', 'Attendance_Records', type_='check')
    op.create_check_constraint(
        'ck_attendance_records_status',
        'Attendance_Records',
        "status IN ('one_shift', 'double_shift', 'absent', 'leave', 'duty_off', 'company_off')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_attendance_records_status', 'Attendance_Records', type_='check')
    op.create_check_constraint(
        'ck_attendance_records_status',
        'Attendance_Records',
        "status IN ('one_shift', 'double_shift', 'absent', 'leave', 'duty_off')",
    )
