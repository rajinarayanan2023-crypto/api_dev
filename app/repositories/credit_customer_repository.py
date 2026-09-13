import uuid

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

    async def get_with_details(self, id: uuid.UUID) -> CreditCustomer | None:
        result = await self.session.execute(select(CreditCustomer).options(*_WITH_DETAIL).where(CreditCustomer.id == id))
        return result.scalar_one_or_none()

    async def list_with_details(self, offset: int = 0, limit: int = 500) -> list[CreditCustomer]:
        result = await self.session.execute(
            select(CreditCustomer).options(*_WITH_DETAIL).order_by(CreditCustomer.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all())
