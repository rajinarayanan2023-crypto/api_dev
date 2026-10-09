import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.credit import CreditCustomer, CreditLedgerEntry
from app.repositories.base import BaseRepository

_WITH_DETAIL = (
    selectinload(CreditCustomer.ledger_entries),
    selectinload(CreditCustomer.bills),
)


class CreditCustomerRepository(BaseRepository[CreditCustomer]):
    def __init__(self, session: AsyncSession):
        super().__init__(CreditCustomer, session)

    # name + phone together is what actually identifies a customer (same
    # reasoning as Employee's name + father_name check) — same name alone
    # isn't a real collision on its own, two different people can share one.
    # Case/whitespace-insensitive; a missing phone on both sides (NULL, via
    # coalesce) still counts as a match rather than as "different".
    async def get_by_name_and_phone(
        self, name: str, phone: str | None, exclude_id: uuid.UUID | None = None
    ) -> CreditCustomer | None:
        query = select(CreditCustomer).where(
            func.lower(CreditCustomer.name) == name.strip().lower(),
            func.coalesce(CreditCustomer.phone, "") == (phone or "").strip(),
        )
        if exclude_id is not None:
            query = query.where(CreditCustomer.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_ledger_entry(self, entry_id: uuid.UUID) -> CreditLedgerEntry | None:
        result = await self.session.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.id == entry_id))
        return result.scalar_one_or_none()

    # Acquires a row lock on this customer for the rest of the current
    # transaction, so two near-simultaneous "add ledger entry" requests for
    # the SAME customer can't both pass the recent-duplicate check below
    # before either has saved — serializing them is what makes that check
    # actually reliable instead of having its own race window.
    async def lock_for_update(self, customer_id: uuid.UUID) -> None:
        await self.session.execute(select(CreditCustomer.id).where(CreditCustomer.id == customer_id).with_for_update())

    # Catches a double-click or two staff both recording the same real-world
    # payment/credit within moments of each other — an exact match on the
    # identifying fields (customer, type, date, amount), created within the
    # last few seconds. Deliberately narrow and time-boxed: a genuinely
    # separate transaction that happens to share the same date/amount later
    # the same day (e.g. two real credit sales) is NOT a duplicate and must
    # never be blocked — only something created moments ago is suspect.
    async def get_recent_duplicate_ledger_entry(
        self, customer_id: uuid.UUID, type: str, entry_date, amount, within_seconds: int = 10
    ) -> CreditLedgerEntry | None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        result = await self.session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.customer_id == customer_id,
                CreditLedgerEntry.type == type,
                CreditLedgerEntry.date == entry_date,
                CreditLedgerEntry.amount == amount,
                CreditLedgerEntry.created_at >= cutoff,
            )
        )
        return result.scalars().first()

    async def get_with_details(self, id: uuid.UUID) -> CreditCustomer | None:
        result = await self.session.execute(select(CreditCustomer).options(*_WITH_DETAIL).where(CreditCustomer.id == id))
        return result.scalar_one_or_none()

    async def list_with_details(self, offset: int = 0, limit: int = 500) -> list[CreditCustomer]:
        result = await self.session.execute(
            select(CreditCustomer).options(*_WITH_DETAIL).order_by(CreditCustomer.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all())
