from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.offer import OfferCustomer
from app.repositories.base import BaseRepository


class OfferCustomerRepository(BaseRepository[OfferCustomer]):
    def __init__(self, session: AsyncSession):
        super().__init__(OfferCustomer, session)

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[OfferCustomer]:
        result = await self.session.execute(
            select(OfferCustomer).order_by(OfferCustomer.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    # Case-insensitive — "Ravi" and "ravi" are the same recipient, same as
    # the lubricant/employee name-dedup convention elsewhere in the app.
    # Only ever matches active rows: an inactive one is a leftover from
    # before this screen switched to hard-delete (a customer "removed" back
    # when removal only ever meant `active = false`) — without this filter,
    # that dead row would block reusing its name forever even though it's
    # already invisible everywhere else in the app.
    async def get_by_name_ci(self, name: str, exclude_id: UUID | None = None) -> OfferCustomer | None:
        query = select(OfferCustomer).where(
            func.lower(OfferCustomer.name) == name.strip().lower(), OfferCustomer.active.is_(True)
        )
        if exclude_id is not None:
            query = query.where(OfferCustomer.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    # Phone numbers are compared as-typed (not normalized) — good enough to
    # catch the actual duplicate-entry mistake this check exists for (the
    # same digits pasted in twice), without guessing at a canonical format.
    # Same active-only scoping as get_by_name_ci above, and for the same reason.
    async def get_by_phone(self, phone: str, exclude_id: UUID | None = None) -> OfferCustomer | None:
        query = select(OfferCustomer).where(OfferCustomer.phone == phone.strip(), OfferCustomer.active.is_(True))
        if exclude_id is not None:
            query = query.where(OfferCustomer.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalars().first()
