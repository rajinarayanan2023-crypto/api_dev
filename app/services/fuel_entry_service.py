import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_dashboard_month
from app.core.database import queue_file_deletion
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models.credit import CreditCustomer, CreditLedgerEntry
from app.models.employee import Employee, EmployeeCredit
from app.models.fuel_entry import FuelEntry, FuelEntryBill, FuelEntryOilRow, FuelReading, PaymentLine
from app.models.user import User
from app.repositories.fuel_entry_repository import FuelEntryRepository
from app.repositories.fuel_stock_log_repository import FuelStockLogRepository
from app.repositories.lubricant_repository import LubricantRepository
from app.schemas.fuel_entry import FuelEntryWrite
from app.services.audit import attach_actor_names
from app.services.salary_period_closure_service import SalaryPeriodClosureService

_FUEL_KEYS = ("petrol", "diesel", "oil")
_NOZZLE_KEYS = ("nozzle1", "nozzle2")


def _reading_liters(opening: Decimal, closing: Decimal, testing: Decimal) -> Decimal:
    return max(Decimal("0"), closing - opening - testing)


def _reading_amount(opening: Decimal, closing: Decimal, testing: Decimal, rate: Decimal) -> Decimal:
    return _reading_liters(opening, closing, testing) * rate


# (total_sale_amount, total_payments) for one entry — mirrors _serialize's
# own totals exactly (same cane_oil_offer discount, floored at 0), factored
# out so _apply_shift_variance_credit can use the identical numbers without
# duplicating _serialize's larger per-nozzle/per-row breakdown.
def _shift_totals(entry: FuelEntry) -> tuple[Decimal, Decimal]:
    fuel_amount_total = Decimal("0")
    for r in entry.readings:
        fuel_amount_total += _reading_amount(r.opening, r.closing, r.testing, r.rate)

    pocket_oil_total = Decimal("0")
    cane_oil_raw_total = Decimal("0")
    for row in entry.oil_rows:
        amount = (row.stock_count or Decimal("0")) * (row.stock_rate or Decimal("0"))
        if row.row_type == "pocket":
            pocket_oil_total += amount
        else:
            cane_oil_raw_total += amount
    cane_oil_total = max(Decimal("0"), cane_oil_raw_total - (entry.cane_oil_offer or Decimal("0")))

    total_sale_amount = fuel_amount_total + pocket_oil_total + cane_oil_total
    total_payments = sum((p.amount or Decimal("0") for p in entry.payment_lines), Decimal("0"))
    return total_sale_amount, total_payments


_FUEL_LABELS = {"petrol": "Petrol", "diesel": "Diesel", "oil": "Oil"}
_NOZZLE_LABELS = {"nozzle1": "Nozzle 1", "nozzle2": "Nozzle 2"}


def _validate_final_readings(data: FuelEntryWrite) -> None:
    """A final entry's numbers are real, reported revenue, so they're only
    allowed to be physically sane. Only checked on a status='final' save
    (never a draft, which is still a work in progress) and per-reading:

    - closing - opening - testing < 0 is impossible for a real meter (it
      only ever counts up through a shift, and testing draws down from
      whatever it actually counted) — rejected outright rather than silently
      treated as "0 litres sold" (see _reading_liters' own floor at 0), which
      would hide exactly the kind of backwards/reset reading, or a Testing
      value bigger than what the meter actually moved, that a fuel inspector
      would flag. Mirrors the UI's own isReadingClosingTooLow in
      PumpDayEditor.jsx exactly — this used to only check closing < opening,
      silently accepting (as a quiet 0-litre reading) a save the UI itself
      already refuses to allow, reachable only by calling this API directly
      rather than through a day-to-day mistake in the app.
    - A reading with real litres sold but rate left at 0 would otherwise
      silently record that fuel as given away for free. A genuinely unused
      nozzle (0 litres) legitimately has no rate to set, so this only fires
      when there's an actual positive litres figure attached to it.
    """
    if data.status != "final":
        return
    nozzles_by_fuel = {"petrol": data.petrol, "diesel": data.diesel, "oil": data.oil}
    for fuel_key in _FUEL_KEYS:
        nozzles = nozzles_by_fuel[fuel_key]
        if nozzles is None:
            continue
        for nozzle_key in _NOZZLE_KEYS:
            r = getattr(nozzles, nozzle_key)
            label = f"{_FUEL_LABELS[fuel_key]} {_NOZZLE_LABELS[nozzle_key]}"
            if (r.closing - r.opening - r.testing) < 0:
                raise AppError(
                    f"{label}: closing reading ({r.closing}) is less than opening ({r.opening}) plus "
                    f"testing ({r.testing}) — check the meter readings before finalizing."
                )
            if _reading_liters(r.opening, r.closing, r.testing) > 0 and r.rate <= 0:
                raise AppError(f"{label} has litres sold but no rate set — enter a rate before finalizing.")


class FuelEntryService:
    """Owns the full save-time cascade Fuel Entry drives into other
    modules — credit ledger, employee credit, and Pump 2 oil stock. A Fuel
    Entry's employee_id is kept purely as a reference (who worked the
    shift); it deliberately does NOT drive Attendance in any way — Attendance
    is managed entirely by hand on its own screen and salary is calculated
    from those manual records only. See ui/src/context/DataContext.jsx's
    applyCreditLedgerFromEntry/applyEmployeeCreditFromEntry/
    applyOilStockFromEntry, which this reproduces exactly.

    None of these side effects fire for a draft — only a 'final' save
    triggers them.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.entries = FuelEntryRepository(session)
        self.stock_logs = FuelStockLogRepository(session)
        self.period_closures = SalaryPeriodClosureService(session)

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

    # Checked on every save (draft or final), not just _build_payments'
    # payment-line employee_id checks — a stale/nonexistent top-level
    # employee_id is the same class of "vanishing reference" bug those
    # guard against. Required outright only when finalizing: a final shift's
    # cash shortage/excess (see _apply_shift_variance_credit) needs someone
    # to tie it to, or that money goes completely untracked.
    async def _validate_shift_employee(self, data: FuelEntryWrite) -> None:
        if data.employee_id is None:
            if data.status == "final":
                raise AppError("An employee must be assigned to finalize a shift entry.")
            return
        result = await self.session.execute(select(Employee.id).where(Employee.id == data.employee_id))
        if result.scalar_one_or_none() is None:
            raise AppError(
                "The employee assigned to this shift no longer exists — please re-select an employee before saving."
            )

    async def _build_payments(self, data: FuelEntryWrite) -> list[PaymentLine]:
        # Payment_Lines.customer_id/employee_id are themselves real FKs (not
        # just the credit-ledger/employee-credit cascade below). Credit Bills
        # CRUD is a complete, real feature now (customer records are no
        # longer "largely mock"), so a 'credit'/'employee_credit' line naming
        # a customer/employee that doesn't resolve is a genuine data problem,
        # not an expected gap to paper over — it used to be silently dropped
        # (the entry still saved, the ledger effect just vanished with it:
        # money left the pump with no record of who owes it), which is
        # exactly the failure this now rejects instead.
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

        for p in data.payments:
            if not p.amount or p.amount <= 0:
                continue
            if p.type == "credit" and p.customer_id and p.customer_id not in valid_customer_ids:
                raise AppError(
                    f"The customer selected for the credit line \"{p.label or 'Credit'}\" no longer exists — "
                    "please re-select a customer before saving."
                )
            if p.type == "employee_credit" and p.employee_id and p.employee_id not in valid_employee_ids:
                raise AppError(
                    f"The employee selected for the credit line \"{p.label or 'Employee Credit'}\" no longer "
                    "exists — please re-select an employee before saving."
                )

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

    async def _apply_write(self, entry: FuelEntry, data: FuelEntryWrite) -> set[str]:
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
        #
        # The actual R2 deletion is NOT done here — the caller queues these
        # keys via queue_file_deletion (see create()/update() below), which
        # only actually deletes them once get_db's wrapper confirms this
        # whole request's transaction has committed. delete_object() is
        # irreversible and can't be rolled back the way the transaction can:
        # deleting right after THIS flush() isn't actually safe either, since
        # flush only sends pending SQL — it doesn't commit it, and a later
        # failure (elsewhere in this same request, or the commit itself)
        # would still roll back the DB change while the R2 object stayed
        # deleted, leaving a bill ROW pointing at a file that no longer
        # exists.
        existing_bills = list(entry.bills)
        removed_keys = {b.file_url for b in existing_bills} - {b.file_url for b in data.bills}
        entry.bills = self._build_bills(data, existing_bills)
        return removed_keys

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

    # carry_forward_bills: {customer_id: [(bill_file_name, bill_file_url), ...]}
    # — bills from the OLD credit-ledger rows this same edit's
    # _remove_credit_ledger_by_source just deleted (see update()), keyed by
    # customer so they can be reattached to whichever NEW row ends up
    # covering that same customer. CreditBills.jsx's handleTxBillUpload
    # explicitly documents attaching a bill straight onto a Fuel-Entry-
    # sourced credit row as ITS intended way to give one of these a receipt
    # (Fuel Entry's own form has no bill upload for a credit line) — but
    # every save of this entry (even one that only touches an unrelated
    # reading, with the credit line itself untouched) used to unconditionally
    # delete and recreate every one of its credit-ledger rows, silently
    # destroying that bill's reference and leaking its R2 object forever
    # with nothing ever cleaning it up. Any bill left unclaimed once every
    # new row has had a chance to take one (the customer's credit line was
    # removed entirely, or there were more old bills than new rows for them)
    # gets queued for real R2 deletion instead of leaking.
    async def _apply_credit_ledger(
        self, entry: FuelEntry, carry_forward_bills: dict[uuid.UUID, list[tuple[str, str]]] | None = None
    ) -> None:
        carry_forward_bills = carry_forward_bills or {}
        candidate_ids = {p.customer_id for p in entry.payment_lines if p.type == "credit" and p.customer_id and p.amount and p.amount > 0}
        valid_ids: set[uuid.UUID] = set()
        if candidate_ids:
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
            carried = carry_forward_bills.get(p.customer_id)
            bill_name, bill_url = carried.pop(0) if carried else (None, None)
            self.session.add(
                CreditLedgerEntry(
                    customer_id=p.customer_id,
                    date=entry.date,
                    type="credit",
                    amount=p.amount,
                    note=(p.note or "").strip() or f"Fuel Entry — {pump_label} · Shift {entry.shift_number}",
                    source_fuel_entry_id=entry.id,
                    bill_file_name=bill_name,
                    bill_file_url=bill_url,
                )
            )
        await self._queue_unclaimed_bills(carry_forward_bills)
        await self.session.flush()

    # Whatever's left in carry_forward_bills after _apply_credit_ledger has
    # had its chance to reclaim entries from it is genuinely orphaned now —
    # queued for a real R2 delete (not left leaking) via the same deferred,
    # commit-gated mechanism Fuel Entry's own bills use (see queue_file_deletion).
    async def _queue_unclaimed_bills(self, carry_forward_bills: dict[uuid.UUID, list[tuple[str, str]]]) -> None:
        for bills in carry_forward_bills.values():
            for _name, key in bills:
                queue_file_deletion(self.session, key)

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
                    type="credit",
                    note=(p.note or "").strip() or f"Fuel Entry — {pump_label} · Shift {entry.shift_number}",
                    source_fuel_entry_id=entry.id,
                )
            )
        await self.session.flush()

    # Ties the shift's own cash shortage/excess (total_payments -
    # total_sale_amount — the same figure FuelEntryOut.excess_shortage shows)
    # to whoever worked it, so it's not just a number on screen — it actually
    # affects pay. A shortage is money the employee owes back (type='credit',
    # deducted from pay, same direction as an advance); an excess is money
    # owed back TO the employee (type='excess', added to pay). One row per
    # entry, fully regenerated on every save exactly like
    # _apply_employee_credit above — editing the entry's readings/payments
    # naturally keeps this in sync, and _remove_employee_credit_by_source
    # already deletes it (same source_fuel_entry_id) before this re-adds it.
    async def _apply_shift_variance_credit(self, entry: FuelEntry) -> None:
        if not entry.employee_id:
            return
        total_sale_amount, total_payments = _shift_totals(entry)
        variance = total_payments - total_sale_amount
        if not variance:
            return
        result = await self.session.execute(select(Employee.id).where(Employee.id == entry.employee_id))
        if result.scalar_one_or_none() is None:
            # Same "don't let a stale reference silently corrupt a ledger"
            # reasoning as elsewhere — but _validate_shift_employee already
            # rejects the save itself in this case, so this is only ever hit
            # if the employee was deleted in the moment between that check
            # and this side effect (ON DELETE SET NULL elsewhere means this
            # can't happen mid-transaction, but costs nothing to guard).
            return
        pump_label = "Pump 1" if entry.pump_key == "pump1" else "Pump 2"
        is_shortage = variance < 0
        self.session.add(
            EmployeeCredit(
                employee_id=entry.employee_id,
                date=entry.date,
                amount=abs(variance),
                type="credit" if is_shortage else "excess",
                note=f"Fuel Entry — {pump_label} · Shift {entry.shift_number} · {'Shortage' if is_shortage else 'Excess'}",
                source_fuel_entry_id=entry.id,
            )
        )
        await self.session.flush()

    async def _adjust_stock(self, product_id: uuid.UUID | None, delta: Decimal) -> None:
        if not product_id or not delta:
            return
        lubricants = LubricantRepository(self.session)
        # Closes the same race LubricantService's own purchase add/edit/
        # delete guard against — this is the OTHER code path that mutates
        # the same product.stock column (a Pump 2 oil sale), and without the
        # same lock here, a purchase and a sale finalized at nearly the same
        # instant could each read the same starting stock value and one
        # change silently overwrites the other.
        await lubricants.lock_for_update(product_id)
        product = await lubricants.get(product_id)
        if product is None:
            return
        resulting_stock = (product.stock or Decimal("0")) + delta
        # Only guarded going DOWN (a sale) — never on a positive delta
        # (reversing a previous sale before an edit/delete rebuilds it, or
        # restoring stock on delete). LubricantService's own purchase
        # edit/delete already refuses to let a correction drive stock
        # negative (see update_purchase/delete_purchase); this was the one
        # other code path writing the same column with no equivalent check
        # at all — two Pump 2 sales racing against the same low-stock
        # product could each pass the UI's own client-side availability
        # check (both reading the same starting figure before either
        # commits) and still both reach here, one after the other under
        # this same lock, with nothing stopping the second from taking it
        # negative.
        if delta < 0 and resulting_stock < 0:
            raise ConflictError(
                f"Not enough {product.name} in stock for this sale — only {product.stock} {product.unit} "
                "left. Reduce the count sold, or record a new purchase first."
            )
        product.stock = resulting_stock
        await self.session.flush()

    # 2T oil (machine) is a nozzle-metered fuel sale, tracked in litres via
    # `entry.readings` exactly like petrol/diesel — it settles into the
    # day's sale/litres totals through the same readings math those use,
    # and never touches Lubricant_Products.stock (there's no catalog
    # product it corresponds to). Pocket oil and Servo/cane oil are the
    # opposite: real catalog products (created in the Lubricants section),
    # sold by the piece — every row below decrements exactly the product it
    # named by exactly the count actually sold, the same "purchase count"
    # the Lubricants page itself reduces on a sale. The two were previously
    # conflated (machine litres were also subtracted from whichever product
    # happened to be the first pocket-oil row), which silently turned a
    # whole-piece stock count into a fractional one — removed; only the
    # per-row piece-count loop below still applies.
    async def _apply_oil_stock(self, entry: FuelEntry, sign: int) -> None:
        if entry.pump_key != "pump2":
            return
        for row in entry.oil_rows:
            if row.product_id and row.stock_count:
                await self._adjust_stock(row.product_id, sign * row.stock_count)

    # Returns whatever bill each removed row had attached, grouped by
    # customer — see _apply_credit_ledger's own docstring-comment for why
    # this can't just delete them outright: a bill attached here (the
    # documented way to give a Fuel-Entry-sourced credit a receipt) must
    # survive this same save's regeneration of these rows, not just this
    # one removal step.
    async def _remove_credit_ledger_by_source(self, entry_id: uuid.UUID) -> dict[uuid.UUID, list[tuple[str, str]]]:
        result = await self.session.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.source_fuel_entry_id == entry_id))
        bills_by_customer: dict[uuid.UUID, list[tuple[str, str]]] = {}
        for row in result.scalars().all():
            if row.bill_file_url:
                bills_by_customer.setdefault(row.customer_id, []).append((row.bill_file_name, row.bill_file_url))
            await self.session.delete(row)
        await self.session.flush()
        return bills_by_customer

    async def _remove_employee_credit_by_source(self, entry_id: uuid.UUID) -> None:
        result = await self.session.execute(select(EmployeeCredit).where(EmployeeCredit.source_fuel_entry_id == entry_id))
        for row in result.scalars().all():
            await self.session.delete(row)
        await self.session.flush()

    async def _apply_side_effects(
        self, entry: FuelEntry, carry_forward_bills: dict[uuid.UUID, list[tuple[str, str]]] | None = None
    ) -> None:
        await self._apply_credit_ledger(entry, carry_forward_bills)
        await self._apply_employee_credit(entry)
        await self._apply_shift_variance_credit(entry)
        await self._apply_oil_stock(entry, -1)

    # ---------- public API ----------

    async def create(self, data: FuelEntryWrite, actor: User) -> dict:
        await self._validate_shift_employee(data)
        if data.status == "final":
            _validate_final_readings(data)
            await self.period_closures.ensure_period_open(data.date.year, data.date.month)
        entry = FuelEntry(created_by=actor.id, updated_by=actor.id)
        removed_bill_keys = await self._apply_write(entry, data)
        self.session.add(entry)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if "uq_fuel_entries_date_pump_shift" in str(exc):
                raise ConflictError("A shift entry already exists for this date, pump, and shift number.") from exc
            raise
        if data.status == "final":
            await self._apply_side_effects(entry)
        invalidate_dashboard_month(entry.date.strftime("%Y-%m"))
        full = await self.entries.get_with_details(entry.id)
        await attach_actor_names(self.session, [full])
        result = await self._serialize(full)
        # Queued, not deleted now — a new entry never actually has removed
        # bills, but this stays symmetric with update() below rather than
        # special-casing it away. See queue_file_deletion's docstring for
        # why this can't safely happen before the whole request commits.
        for key in removed_bill_keys:
            queue_file_deletion(self.session, key)
        return result

    async def update(self, entry_id: uuid.UUID, data: FuelEntryWrite, actor: User) -> dict:
        await self._validate_shift_employee(data)
        if data.status == "final":
            _validate_final_readings(data)
        # Row-locked for the rest of this transaction — see
        # get_with_details_for_update's docstring for why: this is what
        # actually closes the concurrent-update race, the frontend-side fix
        # (cancelling a pending autosave before a manual save) only narrows it.
        existing = await self.entries.get_with_details_for_update(entry_id)
        if existing is None:
            raise NotFoundError("Fuel entry not found.")
        # Check both the entry's current period (its employee-credit side
        # effect, if any, is about to be reversed below) and its incoming
        # period (a new one may be about to apply) — a final entry can't be
        # touched in, or moved into, a closed salary month either way.
        if existing.status == "final":
            await self.period_closures.ensure_period_open(existing.date.year, existing.date.month)
        if data.status == "final":
            await self.period_closures.ensure_period_open(data.date.year, data.date.month)
        previous_month = existing.date.strftime("%Y-%m")

        # Reverse this entry's previous side effects before rebuilding it —
        # attendance is never touched here at all (see class docstring: Fuel
        # Entry keeps employee_id purely as a reference and never drives
        # Attendance in either direction).
        if existing.status == "final":
            await self._apply_oil_stock(existing, 1)
        carry_forward_bills = await self._remove_credit_ledger_by_source(entry_id)
        await self._remove_employee_credit_by_source(entry_id)

        removed_bill_keys = await self._apply_write(existing, data)
        existing.updated_by = actor.id
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if "uq_fuel_entries_date_pump_shift" in str(exc):
                raise ConflictError("A shift entry already exists for this date, pump, and shift number.") from exc
            raise

        if data.status == "final":
            await self._apply_side_effects(existing, carry_forward_bills)
        else:
            # Un-finalizing (or a draft resaved as a draft) — no new credit
            # rows will ever be created for this save to reclaim one of
            # these bills onto, so whatever's here would otherwise leak.
            await self._queue_unclaimed_bills(carry_forward_bills)

        invalidate_dashboard_month(previous_month)
        invalidate_dashboard_month(data.date.strftime("%Y-%m"))
        full = await self.entries.get_with_details(entry_id)
        await attach_actor_names(self.session, [full])
        result = await self._serialize(full)
        # Queued, not deleted now — see queue_file_deletion's docstring.
        for key in removed_bill_keys:
            queue_file_deletion(self.session, key)
        return result

    async def delete(self, entry_id: uuid.UUID) -> None:
        existing = await self.entries.get_with_details(entry_id)
        if existing is None:
            raise NotFoundError("Fuel entry not found.")
        if existing.status == "final":
            await self.period_closures.ensure_period_open(existing.date.year, existing.date.month)
            await self._apply_oil_stock(existing, 1)
        carry_forward_bills = await self._remove_credit_ledger_by_source(entry_id)
        # The entry itself is being deleted outright — nothing will ever
        # reclaim one of these onto a new row, so every one of them needs
        # cleaning up here instead of leaking (see _apply_credit_ledger).
        await self._queue_unclaimed_bills(carry_forward_bills)
        await self._remove_employee_credit_by_source(entry_id)
        bill_keys = [b.file_url for b in existing.bills]
        invalidate_dashboard_month(existing.date.strftime("%Y-%m"))
        deleted_date, deleted_is_shift3 = existing.date, existing.shift_number == 3
        await self.entries.delete(existing)
        # If that was the LAST entry in this (date, is_shift3) scope, any
        # saved Fuel_Stock_Log checkpoint for it is now orphaned — its Sold
        # figure would compute as 0 (nothing left to read a meter boundary
        # from), and worse, a later date's own Opening Stock default would
        # still silently carry forward from it (see AuditModal.jsx's
        # previousStockCheckpoint) as if it were still a real reading.
        # Deleting one of SEVERAL entries in a scope that still has others
        # left must NOT trigger this — the checkpoint is still perfectly
        # valid, backed by what's left, and re-typing Opening Stock/Stock
        # Received on every routine shift correction would be needless
        # busywork for the manager.
        remaining = await self.entries.count_for_date_scope(deleted_date, deleted_is_shift3)
        if remaining == 0:
            orphaned_log = await self.stock_logs.get_by_date(deleted_date, deleted_is_shift3)
            if orphaned_log is not None:
                await self.stock_logs.delete(orphaned_log)
        for key in bill_keys:
            queue_file_deletion(self.session, key)

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
