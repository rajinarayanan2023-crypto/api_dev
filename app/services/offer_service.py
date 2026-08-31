import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.credit import CreditCustomer
from app.models.offer import OfferSend, OfferSendRecipient
from app.models.user import User
from app.repositories.offer_repository import OfferSendRepository
from app.schemas.offer import OfferSendCreate
from app.services.audit import attach_actor_names


async def _attach_recipient_names(session: AsyncSession, sends: list[OfferSend]) -> None:
    ids = {r.customer_id for send in sends for r in send.recipients}
    names: dict[uuid.UUID, str] = {}
    if ids:
        result = await session.execute(select(CreditCustomer.id, CreditCustomer.name).where(CreditCustomer.id.in_(ids)))
        names = dict(result.all())
    for send in sends:
        for r in send.recipients:
            r.customer_name = names.get(r.customer_id, "Unknown customer")


class OfferService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.sends = OfferSendRepository(session)

    async def send(self, data: OfferSendCreate, actor: User) -> OfferSend:
        result = await self.session.execute(
            select(CreditCustomer.id).where(CreditCustomer.id.in_(data.customer_ids))
        )
        found_ids = {row[0] for row in result.all()}
        missing = set(data.customer_ids) - found_ids
        if missing:
            raise NotFoundError("One or more selected customers no longer exist.")

        send = OfferSend(message=data.message, created_by=actor.id, updated_by=actor.id)
        send.recipients = [OfferSendRecipient(customer_id=cid) for cid in data.customer_ids]
        created = await self.sends.create(send)

        # create() only refreshes the OfferSend row itself, not the
        # recipients relationship (already loaded via the assignment above,
        # but each row needs its DB-assigned id + a fresh session identity) —
        # re-fetch with recipients eagerly loaded so serialization is safe.
        full = await self.sends.get_with_recipients(created.id)
        await attach_actor_names(self.session, [full])
        await _attach_recipient_names(self.session, [full])
        return full

    async def list_all(self, offset: int = 0, limit: int = 100) -> list[OfferSend]:
        sends = await self.sends.list_with_recipients(offset=offset, limit=limit)
        await attach_actor_names(self.session, sends)
        await _attach_recipient_names(self.session, sends)
        return sends
