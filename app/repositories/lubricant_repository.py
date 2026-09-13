import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fuel_entry import FuelEntry, FuelEntryOilRow
from app.models.lubricant import LubricantProduct, LubricantPurchaseHistory, LubricantPriceHistory
from app.repositories.base import BaseRepository

_WITH_HISTORY = (
    selectinload(LubricantProduct.price_history),
    selectinload(LubricantProduct.purchase_history),
)


class LubricantRepository(BaseRepository[LubricantProduct]):
    def __init__(self, session: AsyncSession):
        super().__init__(LubricantProduct, session)

    async def get_by_name_ci(self, name: str) -> LubricantProduct | None:
        result = await self.session.execute(
            select(LubricantProduct).where(func.lower(LubricantProduct.name) == name.strip().lower())
        )
        return result.scalars().first()

    async def get_with_history(self, id: uuid.UUID) -> LubricantProduct | None:
        result = await self.session.execute(
            select(LubricantProduct).options(*_WITH_HISTORY).where(LubricantProduct.id == id)
        )
        return result.scalar_one_or_none()

    async def list_with_history(self, offset: int = 0, limit: int = 100) -> list[LubricantProduct]:
        result = await self.session.execute(
            select(LubricantProduct).options(*_WITH_HISTORY).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def add_price_revision(self, revision: LubricantPriceHistory) -> LubricantPriceHistory:
        self.session.add(revision)
        await self.session.flush()
        await self.session.refresh(revision)
        return revision

    async def add_purchase(self, purchase: LubricantPurchaseHistory) -> LubricantPurchaseHistory:
        self.session.add(purchase)
        await self.session.flush()
        await self.session.refresh(purchase)
        return purchase

    async def delete_purchase(self, purchase: LubricantPurchaseHistory) -> None:
        await self.session.delete(purchase)
        await self.session.flush()

    # Fuel_Entry_Oil_Rows.product_id is ON DELETE SET NULL, so the DB itself
    # would silently let a delete through and null out every past sale's
    # product reference instead of rejecting it — this is the check that
    # stops that before it happens.
    async def has_fuel_entry_oil_rows(self, product_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(exists().where(FuelEntryOilRow.product_id == product_id))
        )
        return bool(result.scalar())

    # Every real sale of this product, one row per Fuel Entry oil row —
    # only from 'final' shift entries, since a draft's rows aren't a
    # confirmed sale yet (and get discarded/rewritten freely).
    async def get_sales_history(self, product_id: uuid.UUID) -> list[tuple[FuelEntryOilRow, FuelEntry]]:
        result = await self.session.execute(
            select(FuelEntryOilRow, FuelEntry)
            .join(FuelEntry, FuelEntryOilRow.fuel_entry_id == FuelEntry.id)
            .where(FuelEntryOilRow.product_id == product_id, FuelEntry.status == "final")
            .order_by(FuelEntry.date.desc())
        )
        return [(row, entry) for row, entry in result.all()]

    # One aggregate query for every product's card — last-sold date and
    # total units ever sold, so the catalog list doesn't pay for N
    # separate per-product queries just to show that summary at a glance.
    async def get_sales_summary(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(
                FuelEntryOilRow.product_id,
                func.max(FuelEntry.date),
                func.sum(FuelEntryOilRow.stock_count),
            )
            .join(FuelEntry, FuelEntryOilRow.fuel_entry_id == FuelEntry.id)
            .where(FuelEntryOilRow.product_id.in_(product_ids), FuelEntry.status == "final")
            .group_by(FuelEntryOilRow.product_id)
        )
        return {product_id: (last_date, total_qty) for product_id, last_date, total_qty in result.all()}
