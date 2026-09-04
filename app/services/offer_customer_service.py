import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
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
        customer = OfferCustomer(name=data.name, phone=data.phone)
        return await self.customers.create(customer)

    async def update(self, customer_id: uuid.UUID, data: OfferCustomerUpdate) -> OfferCustomer:
        customer = await self.customers.get(customer_id)
        if customer is None:
            raise NotFoundError("Offer customer not found.")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(customer, field, value)
        await self.session.flush()
        await self.session.refresh(customer)
        return customer
