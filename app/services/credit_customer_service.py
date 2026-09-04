import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.s3 import delete_object
from app.models.credit import CreditCustomer, CreditCustomerBill, CreditLedgerEntry
from app.models.user import User
from app.repositories.credit_customer_repository import CreditCustomerRepository
from app.schemas.credit_customer import CreditCustomerCreate, CreditCustomerUpdate, CreditLedgerEntryCreate
from app.services.audit import attach_actor_names


def _closing_balance(customer: CreditCustomer) -> Decimal:
    balance = customer.opening_balance or Decimal("0")
    for entry in customer.ledger_entries:
        balance += entry.amount if entry.type == "credit" else -entry.amount
    return balance


def _attach_closing_balance(customers: list[CreditCustomer]) -> None:
    for customer in customers:
        customer.closing_balance = _closing_balance(customer)


class CreditCustomerService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.customers = CreditCustomerRepository(session)

    # Diffs by key (file_url, which holds the R2 key) against whatever's
    # already there, instead of unconditionally building a fresh
    # CreditCustomerBill for every one — mirrors FuelEntryService._build_bills
    # exactly, for the same reason: CreditCustomer.bills is cascade="all,
    # delete-orphan", so SQLAlchemy diffs a collection replacement by object
    # identity, not column equality. Reusing the existing row for an
    # unchanged key is what makes it a true no-op on flush; a freshly-built
    # instance would look like a different row and get orphan-deleted +
    # reinserted even though nothing changed. On create there's nothing to
    # match against, so every bill is naturally new.
    def _bills_from(self, bills, existing_bills: list[CreditCustomerBill] = ()) -> list[CreditCustomerBill]:
        existing_by_key = {b.file_url: b for b in existing_bills}
        return [
            existing_by_key.get(b.file_url)
            or CreditCustomerBill(file_name=b.file_name, file_url=b.file_url, uploaded_date=b.uploaded_date)
            for b in bills
        ]

    async def create(self, data: CreditCustomerCreate, actor: User) -> CreditCustomer:
        customer = CreditCustomer(
            name=data.name,
            phone=data.phone,
            opening_balance=data.opening_balance,
            notes=data.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        customer.bills = self._bills_from(data.bills)
        created = await self.customers.create(customer)
        return await self.get(created.id)

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[CreditCustomer]:
        customers = await self.customers.list_with_details(offset=offset, limit=limit)
        await attach_actor_names(self.session, customers)
        _attach_closing_balance(customers)
        return customers

    async def get(self, customer_id: uuid.UUID) -> CreditCustomer:
        customer = await self.customers.get_with_details(customer_id)
        if customer is None:
            raise NotFoundError("Credit customer not found.")
        await attach_actor_names(self.session, [customer])
        _attach_closing_balance([customer])
        return customer

    async def update(self, customer_id: uuid.UUID, data: CreditCustomerUpdate, actor: User) -> CreditCustomer:
        customer = await self.customers.get_with_details(customer_id)
        if customer is None:
            raise NotFoundError("Credit customer not found.")
        updates = data.model_dump(exclude_unset=True, exclude={"bills"})
        for field, value in updates.items():
            setattr(customer, field, value)
        removed_keys: set[str] = set()
        if data.bills is not None:
            existing_bills = list(customer.bills)
            removed_keys = {b.file_url for b in existing_bills} - {b.file_url for b in data.bills}
            customer.bills = self._bills_from(data.bills, existing_bills)
        if updates or data.bills is not None:
            customer.updated_by = actor.id
        await self.session.flush()
        for key in removed_keys:
            delete_object(key)
        return await self.get(customer_id)

    async def delete(self, customer_id: uuid.UUID) -> None:
        customer = await self.customers.get_with_details(customer_id)
        if customer is None:
            raise NotFoundError("Credit customer not found.")
        # Every bill/document tied to this customer — its own Bills &
        # Documents plus any per-ledger-entry attachment — is about to
        # cascade-delete in Postgres along with it; clean up the matching R2
        # objects too so deleting a customer doesn't leave them orphaned.
        bill_keys = [b.file_url for b in customer.bills]
        bill_keys += [e.bill_file_url for e in customer.ledger_entries if e.bill_file_url]
        await self.customers.delete(customer)
        for key in bill_keys:
            delete_object(key)

    async def add_ledger_entry(self, customer_id: uuid.UUID, data: CreditLedgerEntryCreate, actor: User) -> CreditCustomer:
        customer = await self.customers.get_with_details(customer_id)
        if customer is None:
            raise NotFoundError("Credit customer not found.")
        entry = CreditLedgerEntry(
            date=data.date,
            type=data.type,
            fuel_type=data.fuel_type,
            litres=data.litres,
            rate=data.rate,
            amount=data.amount,
            mode=data.mode,
            note=data.note,
            bill_file_name=data.bill_file_name,
            bill_file_url=data.bill_file_url,
        )
        # Appending to the relationship (rather than session.add(entry) with
        # customer_id set directly) is what keeps the already-loaded
        # customer.ledger_entries collection in sync in memory — a plain
        # session.add() still inserts the row correctly, but a subsequent
        # fetch of this same customer returns the SAME cached object from
        # the session's identity map with its relationship collection
        # untouched, so the new entry would look missing until next request.
        customer.ledger_entries.append(entry)
        customer.updated_by = actor.id
        await self.session.flush()
        return await self.get(customer_id)

    # Mirrors the UI's own rule (see CreditBills.jsx) — an entry created from
    # a real Fuel Entry payment line stays tied to it; only manually-added
    # rows (here, or via the Audit modal) can be removed directly.
    async def delete_ledger_entry(self, customer_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        entry = await self.customers.get_ledger_entry(entry_id)
        if entry is None or entry.customer_id != customer_id:
            raise NotFoundError("Ledger entry not found.")
        if entry.source_fuel_entry_id is not None:
            raise ConflictError("This entry was created from a Fuel Entry and can't be removed directly.")
        bill_key = entry.bill_file_url
        await self.session.delete(entry)
        await self.session.flush()
        if bill_key:
            delete_object(bill_key)
