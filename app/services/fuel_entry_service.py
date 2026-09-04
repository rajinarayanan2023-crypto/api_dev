import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.s3 import delete_object
from app.models.attendance import AttendanceRecord
from app.models.credit import CreditCustomer, CreditLedgerEntry
from app.models.employee import Employee, EmployeeCredit
from app.models.fuel_entry import FuelEntry, FuelEntryBill, FuelEntryOilRow, FuelReading, PaymentLine
from app.models.user import User
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.fuel_entry_repository import FuelEntryRepository
from app.repositories.lubricant_repository import LubricantRepository
from app.schemas.fuel_entry import FuelEntryWrite
from app.services.audit import attach_actor_names

_FUEL_KEYS = ("petrol", "diesel", "oil")
_NOZZLE_KEYS = ("nozzle1", "nozzle2")


def _reading_liters(opening: Decimal, closing: Decimal, testing: Decimal) -> Decimal:
    return max(Decimal("0"), closing - opening - testing)


def _reading_amount(opening: Decimal, closing: Decimal, testing: Decimal, rate: Decimal) -> Decimal:
    return _reading_liters(opening, closing, testing) * rate


class FuelEntryService:
    """Owns the full save-time cascade Fuel Entry drives into three other
    modules — see ui/src/context/DataContext.jsx's applyAttendanceFromEntry/
    applyCreditLedgerFromEntry/applyEmployeeCreditFromEntry/
    applyOilStockFromEntry, which this reproduces exactly (including their
    accepted quirks — e.g. attendance is only ever forward re-derived from
    the entry's current employee_id, never reversed for a previous one).

    None of these side effects fire for a draft — only a 'final' save
    triggers them, and only a 'final' save requires at least one bill.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.entries = FuelEntryRepository(session)
        self.attendance = AttendanceRepository(session)

    # ---------- assembling ORM rows from a write payload ----------

    def _build_readings(self, data: FuelEntryWrite) -> list[FuelReading]:
        readings: list[FuelReading] = []
        nozzles_by_fuel = {"petrol": data.petrol, "diesel": data.diesel, "oil": data.oil}
        for fuel_key in _FUEL_KEYS:
            nozzles = nozzles_by_fuel[fuel_key]
            if nozzles is None:
                continue
            for nozzle_key in _NOZZLE_KEYS:
                r = getattr(nozzles, nozzle_key)
                readings.append(
                    FuelReading(
                        fuel_type=fuel_key,
                        nozzle=nozzle_key,
                        opening=r.opening,
                        closing=r.closing,
                        testing=r.testing,
                        rate=r.rate,
                    )
                )
        return readings

    def _build_oil_rows(self, data: FuelEntryWrite) -> list[FuelEntryOilRow]:
        rows = [
            FuelEntryOilRow(row_type="pocket", product_id=r.product_id, stock_count=r.stock_count, stock_rate=r.stock_rate)
            for r in data.oil_rows
        ]
        rows += [
            FuelEntryOilRow(row_type="cane", product_id=r.product_id, stock_count=r.stock_count, stock_rate=r.stock_rate)
            for r in data.cane_oil_rows
        ]
        return rows

    async def _build_payments(self, data: FuelEntryWrite) -> list[PaymentLine]:
        # Payment_Lines.customer_id/employee_id are themselves real FKs (not
        # just the credit-ledger/employee-credit cascade below) — a line
        # naming a customer that doesn't resolve to a real Credit_Customers
        # row (Credit Bills CRUD is still deferred; the frontend's customer
        # list is largely mock) would otherwise fail the whole insert with a
        # ForeignKeyViolationError. Per the agreed behavior, the entry still
        # saves — the unresolved reference is just dropped from that one line.
        customer_ids = {p.customer_id for p in data.payments if p.customer_id}
        employee_ids = {p.employee_id for p in data.payments if p.employee_id}
        valid_customer_ids: set[uuid.UUID] = set()
        valid_employee_ids: set[uuid.UUID] = set()
        if customer_ids:
            result = await self.session.execute(select(CreditCustomer.id).where(CreditCustomer.id.in_(customer_ids)))
            valid_customer_ids = {row[0] for row in result.all()}
        if employee_ids:
            result = await self.session.execute(select(Employee.id).where(Employee.id.in_(employee_ids)))
            valid_employee_ids = {row[0] for row in result.all()}

        return [
            PaymentLine(
                label=p.label,
                amount=p.amount,
                type=p.type,
                customer_id=p.customer_id if p.customer_id in valid_customer_ids else None,
                employee_id=p.employee_id if p.employee_id in valid_employee_ids else None,
                note=p.note,
                denominations=p.denominations,
            )
            for p in data.payments
        ]

    # Diffs the incoming payload against whatever bill rows are already on
    # the entry (by file_url, which holds the R2 key — never trust two
    # different keys to be "the same bill") instead of unconditionally
    # building a fresh FuelEntryBill for every one of them. A bill whose key
    # already has a row is reused AS THE SAME PYTHON OBJECT: since
    # FuelEntry.bills is cascade="all, delete-orphan", SQLAlchemy diffs a
    # collection replacement by object identity, not by column equality —
    # reusing the existing instance is what makes an untouched bill a true
    # no-op on flush (no DELETE, no INSERT, no UPDATE), where rebuilding a
    # new instance every time would silently orphan-delete and reinsert it
    # on every single save regardless of whether anything actually changed.
    # Removed keys (a row that existed before but is missing from this
    # payload) get their R2 object deleted by the caller once it knows the
    # full before/after diff — see _apply_write.
    def _build_bills(self, data: FuelEntryWrite, existing_bills: list[FuelEntryBill] = ()) -> list[FuelEntryBill]:
        existing_by_key = {b.file_url: b for b in existing_bills}
        return [
            existing_by_key.get(b.file_url)
            or FuelEntryBill(file_name=b.file_name, file_url=b.file_url, uploaded_date=b.uploaded_date)
            for b in data.bills
        ]

    async def _apply_write(self, entry: FuelEntry, data: FuelEntryWrite) -> None:
        entry.date = data.date
        entry.pump_key = data.pump_key
        entry.shift_number = data.shift_number
        entry.internal_only = data.internal_only
        entry.employee_id = data.employee_id
        entry.status = data.status
        entry.cane_oil_offer = data.cane_oil_offer
        entry.notes = data.notes
        # Full replace of every child collection — cascade="all, delete-orphan"
        # turns clear()+reassign into DELETE-then-INSERT on flush, same "whole
        # thing resubmitted" pattern as ExpenseDay. Fuel_Readings alone has a
        # real unique constraint on (fuel_entry_id, fuel_type, nozzle) — on an
        # UPDATE, the new rows share that same key with the rows they're
        # replacing, so the insert can be flushed before the delete and
        # collide. Clearing and flushing first (a no-op on create, where
        # there's nothing to delete yet) forces the delete to actually
        # happen before the new rows are ever inserted.
        entry.readings = []
        await self.session.flush()
        entry.readings = self._build_readings(data)
        entry.oil_rows = self._build_oil_rows(data)
        entry.payment_lines = await self._build_payments(data)

        # Bills are the one child collection that must NOT follow the
        # unconditional full-replace pattern above: a bill photo already
        # sitting in R2 has no reason to be deleted-and-reinserted in
        # Postgres (and, if it did, would call for deleting-and-reuploading
        # it in R2 too) just because some unrelated field on the same entry
        # changed. Diff by key first, then only the genuinely-removed keys
        # get their R2 object deleted — every unchanged bill costs zero R2
        # calls and zero DB writes.
        existing_bills = list(entry.bills)
        removed_keys = {b.file_url for b in existing_bills} - {b.file_url for b in data.bills}
        entry.bills = self._build_bills(data, existing_bills)
        for key in removed_keys:
            delete_object(key)

    # ---------- serialization ----------

    async def _employee_name(self, employee_id: uuid.UUID | None) -> str | None:
        if employee_id is None:
            return None
        result = await self.session.execute(select(Employee.name).where(Employee.id == employee_id))
        return result.scalar_one_or_none()

    async def _serialize(self, entry: FuelEntry) -> dict:
        by_fuel: dict[str, dict[str, FuelReading]] = {k: {} for k in _FUEL_KEYS}
        for r in entry.readings:
            by_fuel[r.fuel_type][r.nozzle] = r

        def nozzles_out(fuel_key: str):
            rows = by_fuel[fuel_key]
            if not rows:
                return None
            out = {}
            for nozzle_key in _NOZZLE_KEYS:
                r = rows.get(nozzle_key)
                if r is None:
                    out[nozzle_key] = {"opening": Decimal("0"), "closing": Decimal("0"), "testing": Decimal("0"), "rate": Decimal("0"), "liters": Decimal("0"), "amount": Decimal("0")}
                else:
                    liters = _reading_liters(r.opening, r.closing, r.testing)
                    out[nozzle_key] = {
                        "opening": r.opening,
                        "closing": r.closing,
                        "testing": r.testing,
                        "rate": r.rate,
                        "liters": liters,
                        "amount": liters * r.rate,
                    }
            return out

        def zero_nozzles():
            zero = {"opening": Decimal("0"), "closing": Decimal("0"), "testing": Decimal("0"), "rate": Decimal("0"), "liters": Decimal("0"), "amount": Decimal("0")}
            return {"nozzle1": dict(zero), "nozzle2": dict(zero)}

        petrol = nozzles_out("petrol") or zero_nozzles()
        # Was `or petrol` — an entry with no diesel rows echoed petrol's
        # readings back as diesel's. Each fuel now falls back to its own zeros.
        diesel = nozzles_out("diesel") or zero_nozzles()
        oil = nozzles_out("oil")

        fuel_amount_total = Decimal("0")
        for fuel_key in _FUEL_KEYS:
            n = nozzles_out(fuel_key)
            if n:
                fuel_amount_total += n["nozzle1"]["amount"] + n["nozzle2"]["amount"]

        oil_rows_out = []
        cane_oil_rows_out = []
        pocket_oil_total = Decimal("0")
        cane_oil_raw_total = Decimal("0")
        for row in entry.oil_rows:
            amount = (row.stock_count or Decimal("0")) * (row.stock_rate or Decimal("0"))
            payload = {
                "id": row.id,
                "product_id": row.product_id,
                "stock_count": row.stock_count,
                "stock_rate": row.stock_rate,
                "amount": amount,
            }
            if row.row_type == "pocket":
                oil_rows_out.append(payload)
                pocket_oil_total += amount
            else:
                cane_oil_rows_out.append(payload)
                cane_oil_raw_total += amount
        cane_oil_total = max(Decimal("0"), cane_oil_raw_total - (entry.cane_oil_offer or Decimal("0")))

        payments_out = [
            {
                "id": p.id,
                "label": p.label,
                "amount": p.amount,
                "type": p.type,
                "customer_id": p.customer_id,
                "employee_id": p.employee_id,
                "note": p.note,
                "denominations": p.denominations,
            }
            for p in entry.payment_lines
        ]
        total_payments = sum((p.amount or Decimal("0") for p in entry.payment_lines), Decimal("0"))
        total_sale_amount = fuel_amount_total + pocket_oil_total + cane_oil_total

        bills_out = [
            {"id": b.id, "file_name": b.file_name, "file_url": b.file_url, "uploaded_date": b.uploaded_date}
            for b in entry.bills
        ]

        employee_name = await self._employee_name(entry.employee_id)

        return {
            "id": entry.id,
            "date": entry.date,
            "pump_key": entry.pump_key,
            "shift_number": entry.shift_number,
            "internal_only": entry.internal_only,
            "employee_id": entry.employee_id,
            "employee_name": employee_name,
            "status": entry.status,
            "petrol": petrol,
            "diesel": diesel,
            "oil": oil,
            "oil_rows": oil_rows_out,
            "cane_oil_rows": cane_oil_rows_out,
            "cane_oil_offer": entry.cane_oil_offer,
            "payments": payments_out,
            "bills": bills_out,
            "notes": entry.notes,
            "total_sale_amount": total_sale_amount,
            "total_payments": total_payments,
            "excess_shortage": total_payments - total_sale_amount,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "created_by": entry.created_by,
            "created_by_name": getattr(entry, "created_by_name", None),
            "updated_by": entry.updated_by,
            "updated_by_name": getattr(entry, "updated_by_name", None),
        }

    # ---------- side-effect cascade ----------

    async def _upsert_attendance(self, employee_id: uuid.UUID, day, status: str, actor: User) -> None:
        existing = await self.attendance.get_by_employee_and_date(employee_id, day)
        if existing is not None:
            existing.status = status
            existing.updated_by = actor.id
        else:
            self.session.add(
                AttendanceRecord(employee_id=employee_id, date=day, status=status, created_by=actor.id, updated_by=actor.id)
            )
        await self.session.flush()

    async def _apply_attendance(self, entry: FuelEntry, actor: User) -> None:
        if entry.internal_only or entry.employee_id is None:
            return
        count = await self.entries.count_final_for_employee_on_date(entry.employee_id, entry.date)
        status = "double_shift" if count >= 2 else "one_shift"
        await self._upsert_attendance(entry.employee_id, entry.date, status, actor)
        if status == "double_shift":
            next_date = entry.date + timedelta(days=1)
            existing_next = await self.attendance.get_by_employee_and_date(entry.employee_id, next_date)
            if existing_next is None:
                await self._upsert_attendance(entry.employee_id, next_date, "duty_off", actor)

    async def _apply_credit_ledger(self, entry: FuelEntry) -> None:
        candidate_ids = {p.customer_id for p in entry.payment_lines if p.type == "credit" and p.customer_id and p.amount and p.amount > 0}
        if not candidate_ids:
            return
        result = await self.session.execute(select(CreditCustomer.id).where(CreditCustomer.id.in_(candidate_ids)))
        valid_ids = {row[0] for row in result.all()}
        pump_label = "Pump 1" if entry.pump_key == "pump1" else "Pump 2"
        for p in entry.payment_lines:
            if p.type != "credit" or not p.customer_id or not p.amount or p.amount <= 0:
                continue
            if p.customer_id not in valid_ids:
                # Chosen behavior: the fuel entry still saves; this one
                # credit line's ledger effect is silently skipped since it
                # doesn't resolve to a real Credit_Customers row yet (Credit
                # Bills CRUD — create/edit a customer — is still deferred).
                continue
            self.session.add(
                CreditLedgerEntry(
                    customer_id=p.customer_id,
                    date=entry.date,
                    type="credit",
                    amount=p.amount,
                    note=(p.note or "").strip() or f"Fuel Entry — {pump_label} · Shift {entry.shift_number}",
                    source_fuel_entry_id=entry.id,
                )
            )
        await self.session.flush()

    async def _apply_employee_credit(self, entry: FuelEntry) -> None:
        candidate_ids = {p.employee_id for p in entry.payment_lines if p.type == "employee_credit" and p.employee_id and p.amount and p.amount > 0}
        if not candidate_ids:
            return
        result = await self.session.execute(select(Employee.id).where(Employee.id.in_(candidate_ids)))
        valid_ids = {row[0] for row in result.all()}
        pump_label = "Pump 1" if entry.pump_key == "pump1" else "Pump 2"
        for p in entry.payment_lines:
            if p.type != "employee_credit" or not p.employee_id or not p.amount or p.amount <= 0:
                continue
            if p.employee_id not in valid_ids:
                continue
            self.session.add(
                EmployeeCredit(
                    employee_id=p.employee_id,
                    date=entry.date,
                    amount=p.amount,
                    note=(p.note or "").strip() or f"Fuel Entry — {pump_label} · Shift {entry.shift_number}",
                    source_fuel_entry_id=entry.id,
                )
            )
        await self.session.flush()

    async def _adjust_stock(self, product_id: uuid.UUID | None, delta: Decimal) -> None:
        if not product_id or not delta:
            return
        product = await LubricantRepository(self.session).get(product_id)
        if product is None:
            return
        product.stock = (product.stock or Decimal("0")) + delta
        await self.session.flush()

    async def _apply_oil_stock(self, entry: FuelEntry, sign: int) -> None:
        if entry.pump_key != "pump2":
            return
        oil_readings = [r for r in entry.readings if r.fuel_type == "oil"]
        liters = sum((_reading_liters(r.opening, r.closing, r.testing) for r in oil_readings), Decimal("0"))
        pocket_rows = [r for r in entry.oil_rows if r.row_type == "pocket"]
        if pocket_rows and pocket_rows[0].product_id and liters:
            await self._adjust_stock(pocket_rows[0].product_id, sign * liters)
        for row in entry.oil_rows:
            if row.product_id and row.stock_count:
                await self._adjust_stock(row.product_id, sign * row.stock_count)

    async def _remove_credit_ledger_by_source(self, entry_id: uuid.UUID) -> None:
        result = await self.session.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.source_fuel_entry_id == entry_id))
        for row in result.scalars().all():
            await self.session.delete(row)
        await self.session.flush()

    async def _remove_employee_credit_by_source(self, entry_id: uuid.UUID) -> None:
        result = await self.session.execute(select(EmployeeCredit).where(EmployeeCredit.source_fuel_entry_id == entry_id))
        for row in result.scalars().all():
            await self.session.delete(row)
        await self.session.flush()

    async def _apply_side_effects(self, entry: FuelEntry, actor: User) -> None:
        await self._apply_attendance(entry, actor)
        await self._apply_credit_ledger(entry)
        await self._apply_employee_credit(entry)
        await self._apply_oil_stock(entry, -1)

    # ---------- public API ----------

    async def create(self, data: FuelEntryWrite, actor: User) -> dict:
        # Bill-upload requirement temporarily disabled — see update() below.
        # if data.status == "final" and not data.bills:
        #     raise AppError("At least one bill is required to finalize a shift entry.")
        entry = FuelEntry(created_by=actor.id, updated_by=actor.id)
        await self._apply_write(entry, data)
        self.session.add(entry)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if "uq_fuel_entries_date_pump_shift" in str(exc):
                raise ConflictError("A shift entry already exists for this date, pump, and shift number.") from exc
            raise
        if data.status == "final":
            await self._apply_side_effects(entry, actor)
        full = await self.entries.get_with_details(entry.id)
        await attach_actor_names(self.session, [full])
        return await self._serialize(full)

    async def update(self, entry_id: uuid.UUID, data: FuelEntryWrite, actor: User) -> dict:
        # Bill-upload requirement temporarily disabled — a fuel entry can be
        # finalized without a bill for now. Restore these two checks (here
        # and in create() above) to bring the requirement back.
        # if data.status == "final" and not data.bills:
        #     raise AppError("At least one bill is required to finalize a shift entry.")
        # Row-locked for the rest of this transaction — see
        # get_with_details_for_update's docstring for why: this is what
        # actually closes the concurrent-update race, the frontend-side fix
        # (cancelling a pending autosave before a manual save) only narrows it.
        existing = await self.entries.get_with_details_for_update(entry_id)
        if existing is None:
            raise NotFoundError("Fuel entry not found.")

        # Reverse this entry's previous side effects before rebuilding it —
        # attendance is intentionally NOT reversed here (see class docstring),
        # only re-derived forward below if the new status is final.
        if existing.status == "final":
            await self._apply_oil_stock(existing, 1)
        await self._remove_credit_ledger_by_source(entry_id)
        await self._remove_employee_credit_by_source(entry_id)

        await self._apply_write(existing, data)
        existing.updated_by = actor.id
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if "uq_fuel_entries_date_pump_shift" in str(exc):
                raise ConflictError("A shift entry already exists for this date, pump, and shift number.") from exc
            raise

        if data.status == "final":
            await self._apply_side_effects(existing, actor)

        full = await self.entries.get_with_details(entry_id)
        await attach_actor_names(self.session, [full])
        return await self._serialize(full)

    async def delete(self, entry_id: uuid.UUID) -> None:
        existing = await self.entries.get_with_details(entry_id)
        if existing is None:
            raise NotFoundError("Fuel entry not found.")
        if existing.status == "final":
            await self._apply_oil_stock(existing, 1)
        await self._remove_credit_ledger_by_source(entry_id)
        await self._remove_employee_credit_by_source(entry_id)
        bill_keys = [b.file_url for b in existing.bills]
        await self.entries.delete(existing)
        for key in bill_keys:
            delete_object(key)

    async def get(self, entry_id: uuid.UUID) -> dict:
        entry = await self.entries.get_with_details(entry_id)
        if entry is None:
            raise NotFoundError("Fuel entry not found.")
        await attach_actor_names(self.session, [entry])
        return await self._serialize(entry)

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 1000,
        pump_key: str | None = None,
        entry_date: date | None = None,
        before: date | None = None,
    ) -> list[dict]:
        entries = await self.entries.list_with_details(
            offset=offset, limit=limit, pump_key=pump_key, entry_date=entry_date, before=before
        )
        await attach_actor_names(self.session, entries)
        return [await self._serialize(e) for e in entries]
