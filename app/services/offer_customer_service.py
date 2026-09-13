import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.offer import OfferCustomer
from app.repositories.offer_customer_repository import OfferCustomerRepository
from app.schemas.offer_customer import OfferCustomerCreate, OfferCustomerUpdate


class OfferCustomerService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.customers = OfferCustomerRepository(session)

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[OfferCustomer]:
        return await self.customers.list_all(offset=offset, limit=limit)

    async def create(self, data: OfferCustomerCreate) -> OfferCustomer:
        if await self.customers.get_by_name_ci(data.name) is not None:
            raise ConflictError("A recipient with this name already exists.")
        if data.phone and await self.customers.get_by_phone(data.phone) is not None:
            raise ConflictError("A recipient with this phone number already exists.")
        customer = OfferCustomer(name=data.name, phone=data.phone)
        return await self.customers.create(customer)

    async def update(self, customer_id: uuid.UUID, data: OfferCustomerUpdate) -> OfferCustomer:
        customer = await self.customers.get(customer_id)
        if customer is None:
            raise NotFoundError("Offer customer not found.")
        updates = data.model_dump(exclude_unset=True)
        if "name" in updates and await self.customers.get_by_name_ci(updates["name"], exclude_id=customer_id) is not None:
            raise ConflictError("A recipient with this name already exists.")
        if updates.get("phone") and await self.customers.get_by_phone(updates["phone"], exclude_id=customer_id) is not None:
            raise ConflictError("A recipient with this phone number already exists.")
        for field, value in updates.items():
            setattr(customer, field, value)
        await self.session.flush()
        await self.session.refresh(customer)
        return customer

    # Hard delete (per-screen decision for Offers, unlike the "deactivate,
    # never delete" convention elsewhere) — offer_customers is a standalone
    # table with nothing else in the schema referencing it (see
    # OfferSendRecipient's docstring), so this has zero side effects on any
    # past send's history.
    async def delete(self, customer_id: uuid.UUID) -> None:
        customer = await self.customers.get(customer_id)
        if customer is None:
            raise NotFoundError("Offer customer not found.")
        await self.customers.delete(customer)
