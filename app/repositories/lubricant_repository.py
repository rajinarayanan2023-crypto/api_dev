import uuid
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fuel_entry import FuelEntry, FuelEntryOilRow
from app.models.lubricant import LubricantProduct, LubricantPurchaseHistory
from app.repositories.base import BaseRepository

_WITH_HISTORY = (selectinload(LubricantProduct.purchase_history),)


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

    # Acquires a row lock on this product for the rest of the current
    # transaction — closes the race where two concurrent stock-mutating
    # requests (a purchase and a sale, or two purchases) both read the same
    # starting `stock` value before either has saved, silently dropping one
    # of the two changes on whichever commits second. Callers run this
    # BEFORE reading product.stock; a bare SELECT with no columns loaded is
    # enough since the point is only to hold the lock, not to fetch data.
    async def lock_for_update(self, id: uuid.UUID) -> None:
        await self.session.execute(select(LubricantProduct.id).where(LubricantProduct.id == id).with_for_update())

    async def list_with_history(self, offset: int = 0, limit: int = 100) -> list[LubricantProduct]:
        result = await self.session.execute(
            select(LubricantProduct).options(*_WITH_HISTORY).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

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

    # A saved Pump 2 oil row copies whichever purchase-batch cost the manager
    # picked into its own stock_rate at save time (see FuelEntryService) —
    # it's a snapshot, not a live FK to Lubricant_Purchase_History, but that
    # copied number is still exactly what LubricantService.delete_purchase
    # needs to check before letting a batch disappear out from under a
    # sale that was priced against it. Only 'final' entries count — a
    # draft's rows aren't a confirmed sale yet and get freely
    # discarded/rewritten (same reasoning as get_sales_history above).
    async def has_final_oil_row_at_rate(self, product_id: uuid.UUID, rate) -> bool:
        result = await self.session.execute(
            select(exists().where(
                FuelEntryOilRow.product_id == product_id,
                FuelEntryOilRow.stock_rate == rate,
                FuelEntryOilRow.fuel_entry_id.in_(
                    select(FuelEntry.id).where(FuelEntry.status == "final")
                ),
            ))
        )
        return bool(result.scalar())

    # The actual count already sold out of THIS specific cost batch — not
    # just whether any row exists (has_final_oil_row_at_rate above only
    # answers that), the real total, needed to stop a purchase correction
    # from recording this batch as smaller than what's demonstrably already
    # been sold from it. Scoped the same way: only 'final' entries count.
    async def sum_final_oil_row_count_at_rate(self, product_id: uuid.UUID, rate) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(FuelEntryOilRow.stock_count), 0)).where(
                FuelEntryOilRow.product_id == product_id,
                FuelEntryOilRow.stock_rate == rate,
                FuelEntryOilRow.fuel_entry_id.in_(
                    select(FuelEntry.id).where(FuelEntry.status == "final")
                ),
            )
        )
        return result.scalar_one()

    # Every real sale of this product, one row per Fuel Entry oil row —
    # only from 'final' shift entries, since a draft's rows aren't a
    # confirmed sale yet (and get discarded/rewritten freely). Capped, not
    # paged — this only ever feeds the Lubricants "Sold History" modal's own
    # small scrolling list (never total_sold/last_sold_date, which come from
    # a separate aggregate query in get_sales_summary below), so the most
    # recent `limit` sales is what a manager actually wants to see, not every
    # sale this product has ever had since the day it was added.
    async def get_sales_history(
        self, product_id: uuid.UUID, offset: int = 0, limit: int = 500
    ) -> list[tuple[FuelEntryOilRow, FuelEntry]]:
        result = await self.session.execute(
            select(FuelEntryOilRow, FuelEntry)
            .join(FuelEntry, FuelEntryOilRow.fuel_entry_id == FuelEntry.id)
            .where(FuelEntryOilRow.product_id == product_id, FuelEntry.status == "final")
            .order_by(FuelEntry.date.desc())
            .offset(offset)
            .limit(limit)
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

    # Same idea as get_sales_summary above, but broken down by rate instead
    # of collapsed to one total — the Fuel Entry oil-row picker's "Available"
    # figure for a specific cost needs to know how much has already been
    # sold at THAT cost specifically (see sum_final_oil_row_count_at_rate's
    # own docstring for why a single running product.stock can't answer
    # that), and batching this across every product on the Lubricants list
    # avoids paying for it with a separate query per product per rate.
    async def get_sold_count_by_rate(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[Decimal, Decimal]]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(
                FuelEntryOilRow.product_id,
                FuelEntryOilRow.stock_rate,
                func.sum(FuelEntryOilRow.stock_count),
            )
            .join(FuelEntry, FuelEntryOilRow.fuel_entry_id == FuelEntry.id)
            .where(FuelEntryOilRow.product_id.in_(product_ids), FuelEntry.status == "final")
            .group_by(FuelEntryOilRow.product_id, FuelEntryOilRow.stock_rate)
        )
        out: dict[uuid.UUID, dict[Decimal, Decimal]] = {}
        for product_id, rate, total in result.all():
            out.setdefault(product_id, {})[rate] = total
        return out
