import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.lubricant import LubricantPriceHistory, LubricantProduct, LubricantPurchaseHistory
from app.models.user import User
from app.repositories.lubricant_repository import LubricantRepository
from app.schemas.lubricant import LubricantCreate, LubricantUpdate, PriceHistoryCreate, PurchaseCreate, PurchaseUpdate
from app.services.audit import attach_actor_names


class LubricantService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.products = LubricantRepository(session)

    async def create_product(self, data: LubricantCreate, actor: User) -> LubricantProduct:
        if await self.products.get_by_name_ci(data.name) is not None:
            raise ConflictError("A product with this name already exists.")
        payload = data.model_dump(exclude={"opening_rate", "opening_stock"})
        product = LubricantProduct(**payload, stock=data.opening_stock, created_by=actor.id, updated_by=actor.id)
        today = date.today()
        product.price_history = [LubricantPriceHistory(effective_from=today, rate=data.opening_rate)]
        # Opening stock is itself the product's first purchase (cost 0) —
        # mirrors the old mock data's addLubricant, and keeps
        # stockAvailableAtRate's per-price-period counting correct from day
        # one, once the price is ever revised.
        if data.opening_stock > 0:
            product.purchase_history = [
                LubricantPurchaseHistory(date=today, qty=data.opening_stock, cost=0)
            ]
        created = await self.products.create(product)
        # BaseRepository.create()'s refresh() expires (but does not eagerly
        # reload) relationship attributes, which would otherwise force a
        # lazy-load during Pydantic's synchronous serialization — something
        # AsyncSession can't service outside an active await. Re-fetch with
        # history eagerly loaded instead.
        return await self.get_product(created.id)

    async def _attach_sales_summary(self, products: list[LubricantProduct]) -> None:
        summary = await self.products.get_sales_summary([p.id for p in products])
        for product in products:
            last_date, total_qty = summary.get(product.id, (None, None))
            product.last_sold_date = last_date
            product.total_sold = total_qty or 0

    async def list_products(self, offset: int = 0, limit: int = 100) -> list[LubricantProduct]:
        products = await self.products.list_with_history(offset=offset, limit=limit)
        await attach_actor_names(self.session, products)
        await self._attach_sales_summary(products)
        return products

    async def get_product(self, product_id: uuid.UUID) -> LubricantProduct:
        product = await self.products.get_with_history(product_id)
        if product is None:
            raise NotFoundError("Lubricant product not found.")
        await attach_actor_names(self.session, [product])
        await self._attach_sales_summary([product])
        return product

    async def update_product(self, product_id: uuid.UUID, data: LubricantUpdate, actor: User) -> LubricantProduct:
        product = await self.get_product(product_id)
        updates = data.model_dump(exclude_unset=True)
        if "name" in updates:
            existing = await self.products.get_by_name_ci(updates["name"])
            if existing is not None and existing.id != product_id:
                raise ConflictError("A product with this name already exists.")
        for field, value in updates.items():
            setattr(product, field, value)
        if updates:
            product.updated_by = actor.id
        await self.session.flush()
        if updates:
            # Refresh only the columns just written — an unqualified
            # refresh() also expires (without reloading) relationship
            # attributes like price_history, which would then crash Pydantic
            # serialization by forcing a lazy-load outside an active await.
            await self.session.refresh(product, attribute_names=[*updates.keys(), "updated_by", "updated_at"])
        await attach_actor_names(self.session, [product])
        return product

    # Replaces the existing row instead of inserting a duplicate when
    # effective_from matches one already on record (e.g. a same-day
    # correction to a brand-new product's opening rate) — the table has a
    # unique constraint on (product_id, effective_from), so a plain insert
    # would otherwise raise IntegrityError for what the manager sees as an edit.
    async def add_price_revision(self, product_id: uuid.UUID, data: PriceHistoryCreate, actor: User) -> LubricantProduct:
        product = await self.get_product(product_id)
        existing = next((h for h in product.price_history if h.effective_from == data.effective_from), None)
        if existing is not None:
            existing.rate = data.rate
        else:
            revision = LubricantPriceHistory(
                product_id=product.id, effective_from=data.effective_from, rate=data.rate
            )
            await self.products.add_price_revision(revision)
            # The new row went in through a separate object, not through
            # product.price_history itself, so that already-loaded collection
            # is now stale in the session's identity map — expire it so
            # get_product() below actually re-reads it instead of returning
            # the cached (pre-insert) collection.
            self.session.expire(product, ["price_history"])
        product.updated_by = actor.id
        await self.session.flush()
        return await self.get_product(product_id)

    async def add_purchase(self, product_id: uuid.UUID, data: PurchaseCreate, actor: User) -> LubricantProduct:
        product = await self.get_product(product_id)
        purchase = LubricantPurchaseHistory(
            product_id=product.id, date=data.date, qty=data.qty, cost=data.cost
        )
        await self.products.add_purchase(purchase)
        product.stock = (product.stock or 0) + data.qty
        product.updated_by = actor.id
        # Same staleness issue as add_price_revision above, for purchase_history.
        self.session.expire(product, ["purchase_history"])
        await self.session.flush()
        return await self.get_product(product_id)

    # Corrects a mis-entered purchase (wrong qty/cost/date) after the fact.
    # There's no per-purchase consumption ledger — `product.stock` is one
    # running total, incremented by every purchase and decremented by every
    # sale as they happen (see FuelEntryService._adjust_stock) — so a qty
    # correction can only ever apply as a DELTA against that running total,
    # never as a fresh recompute (recomputing from purchases alone would
    # forget every sale already deducted). If units from the ORIGINAL
    # (wrong) quantity were already sold before this correction, reducing
    # qty enough to outrun what's left in stock would drive it negative —
    # blocked outright rather than silently corrupting the stock count.
    async def update_purchase(
        self, product_id: uuid.UUID, purchase_id: uuid.UUID, data: PurchaseUpdate, actor: User
    ) -> LubricantProduct:
        product = await self.get_product(product_id)
        purchase = next((p for p in product.purchase_history if p.id == purchase_id), None)
        if purchase is None:
            raise NotFoundError("Purchase record not found.")
        updates = data.model_dump(exclude_unset=True)
        if "qty" in updates and updates["qty"] != purchase.qty:
            delta = updates["qty"] - purchase.qty
            resulting_stock = (product.stock or 0) + delta
            if resulting_stock < 0:
                raise ConflictError(
                    f"Can't reduce this purchase to {updates['qty']} {product.unit} — that's "
                    f"{abs(resulting_stock)} {product.unit} more than what's left in stock, since some "
                    "of the original quantity has already been sold. Enter a larger quantity."
                )
            product.stock = resulting_stock
        for field, value in updates.items():
            setattr(purchase, field, value)
        if updates:
            product.updated_by = actor.id
        await self.session.flush()
        self.session.expire(product, ["purchase_history"])
        return await self.get_product(product_id)

    # Same stock-delta safety as update_purchase above, applied as a full
    # removal (delta = -qty) instead of a partial correction.
    async def delete_purchase(self, product_id: uuid.UUID, purchase_id: uuid.UUID, actor: User) -> LubricantProduct:
        product = await self.get_product(product_id)
        purchase = next((p for p in product.purchase_history if p.id == purchase_id), None)
        if purchase is None:
            raise NotFoundError("Purchase record not found.")
        resulting_stock = (product.stock or 0) - purchase.qty
        if resulting_stock < 0:
            raise ConflictError(
                f"Can't remove this purchase — {abs(resulting_stock)} {product.unit} more than "
                "what's left in stock have already been sold since it was recorded. Removing it "
                "would take stock negative."
            )
        product.stock = resulting_stock
        await self.products.delete_purchase(purchase)
        product.updated_by = actor.id
        await self.session.flush()
        self.session.expire(product, ["purchase_history"])
        return await self.get_product(product_id)

    async def get_sales_history(self, product_id: uuid.UUID) -> list[dict]:
        await self.get_product(product_id)  # 404s if the product doesn't exist
        rows = await self.products.get_sales_history(product_id)
        return [
            {
                "fuel_entry_id": entry.id,
                "date": entry.date,
                "pump_key": entry.pump_key,
                "shift_number": entry.shift_number,
                "row_type": row.row_type,
                "qty": row.stock_count,
                "rate": row.stock_rate,
                "amount": row.stock_count * row.stock_rate,
            }
            for row, entry in rows
        ]

    async def delete_product(self, product_id: uuid.UUID) -> None:
        product = await self.get_product(product_id)
        if await self.products.has_fuel_entry_oil_rows(product_id):
            raise ConflictError(
                "This product has been sold in one or more fuel entries and cannot be deleted."
            )
        await self.products.delete(product)
