import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.lubricant import LubricantProduct, LubricantPurchaseHistory
from app.models.user import User
from app.repositories.lubricant_repository import LubricantRepository
from app.schemas.lubricant import LubricantCreate, LubricantUpdate, PurchaseCreate, PurchaseUpdate
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
        # Opening stock is itself the product's first purchase — recorded
        # against the rate just entered (the only price this form actually
        # collects), rather than a hardcoded 0, which showed as an obviously
        # wrong "₹0/unit" in Purchase History for stock the manager had just
        # priced. Not a true acquisition cost (there's no separate "what did
        # you pay for the opening stock" field), but it's the only real
        # figure available here and is far closer to correct than 0 — and it
        # keeps stockAvailableAtRate's per-price-period counting correct from
        # day one, once the price is ever revised, same as before.
        if data.opening_stock > 0:
            product.purchase_history = [
                LubricantPurchaseHistory(
                    date=today, qty=data.opening_stock, cost=data.opening_rate,
                    created_by=actor.id, updated_by=actor.id,
                )
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
        sold_by_rate = await self.products.get_sold_count_by_rate([p.id for p in products])
        for product in products:
            last_date, total_qty = summary.get(product.id, (None, None))
            product.last_sold_date = last_date
            product.total_sold = total_qty or 0
            # Keyed by the rate as a string (Decimal isn't a valid JSON
            # object key) — see LubricantOut.sold_count_by_rate.
            product.sold_count_by_rate = {
                str(rate): qty for rate, qty in sold_by_rate.get(product.id, {}).items()
            }

    async def list_products(self, offset: int = 0, limit: int = 100) -> list[LubricantProduct]:
        products = await self.products.list_with_history(offset=offset, limit=limit)
        await attach_actor_names(self.session, products)
        await attach_actor_names(self.session, [h for p in products for h in p.purchase_history])
        await self._attach_sales_summary(products)
        return products

    async def get_product(self, product_id: uuid.UUID) -> LubricantProduct:
        product = await self.products.get_with_history(product_id)
        if product is None:
            raise NotFoundError("Lubricant product not found.")
        await attach_actor_names(self.session, [product])
        await attach_actor_names(self.session, product.purchase_history)
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
            # attributes like purchase_history, which would then crash
            # Pydantic serialization by forcing a lazy-load outside an
            # active await.
            await self.session.refresh(product, attribute_names=[*updates.keys(), "updated_by", "updated_at"])
        await attach_actor_names(self.session, [product])
        return product

    # Checked before ANY qty reduction (a Record Purchase upsert replacing an
    # existing batch's qty with a smaller one, or a direct edit via
    # update_purchase below) — the more specific, more useful reason first:
    # this exact cost's batch may already have sales against it that the
    # OVERALL running `product.stock` alone can't reveal, since stock is one
    # aggregate column with no idea which batch a past sale came out of. A
    # product with TWO untouched batches (say 12 @ ₹26 and 8 @ ₹25, only the
    # ₹25 one ever sold from) has plenty of overall headroom from the ₹26
    # batch alone — the overall-stock check below would wave through
    # shrinking the ₹25 batch down well past what's actually been sold out
    # of it specifically, silently making "Available" at that rate read as
    # if those already-sold units were still sitting on the shelf. Querying
    # the real per-batch sold count (sum_final_oil_row_count_at_rate) is
    # what actually catches that. The overall-stock check stays too, as a
    # second, cruder backstop for the same class of problem.
    async def _guard_qty_reduction(
        self, product_id: uuid.UUID, cost, new_qty: int, product: LubricantProduct, delta: int
    ) -> Decimal:
        sold_at_rate = await self.products.sum_final_oil_row_count_at_rate(product_id, cost)
        if new_qty < sold_at_rate:
            raise ConflictError(
                f"Can't reduce this purchase (₹{cost} per {product.unit}) to {new_qty} {product.unit} — "
                f"{sold_at_rate} {product.unit} have already been sold out of this exact batch via a saved "
                "Pump 2 fuel entry. Enter a larger quantity."
            )
        resulting_stock = (product.stock or 0) + delta
        if resulting_stock < 0:
            raise ConflictError(
                f"Can't reduce this purchase to {new_qty} {product.unit} — that's "
                f"{abs(resulting_stock)} {product.unit} more than what's left in stock, since some "
                "of the original quantity has already been sold. Enter a larger quantity."
            )
        return resulting_stock

    # Upserts by (date, cost): two "Record Purchase" submissions for the
    # same product, same day, at the same per-unit cost are the same real
    # restock batch (purchaseBatchesByCost already groups/sums them that
    # way) — inserting a second row for it used to just fragment that one
    # batch's history into "+17" / "+12" rows side by side on the same date
    # instead of one. A DIFFERENT cost on the same date is still a genuinely
    # separate batch and still inserts its own row, same as before.
    #
    # Because this can now also shrink an existing row's qty (recording "4"
    # over an existing "17"), it carries the same reduction guard
    # update_purchase has below — increasing the qty is never blocked, only
    # a reduction can ever run into it.
    async def add_purchase(self, product_id: uuid.UUID, data: PurchaseCreate, actor: User) -> LubricantProduct:
        await self.products.lock_for_update(product_id)
        product = await self.get_product(product_id)
        existing = next(
            (p for p in product.purchase_history if p.date == data.date and p.cost == data.cost), None
        )
        if existing is not None:
            delta = data.qty - existing.qty
            if delta < 0:
                resulting_stock = await self._guard_qty_reduction(product_id, data.cost, data.qty, product, delta)
            else:
                resulting_stock = (product.stock or 0) + delta
            existing.qty = data.qty
            existing.updated_by = actor.id
            product.stock = resulting_stock
        else:
            purchase = LubricantPurchaseHistory(
                product_id=product.id, date=data.date, qty=data.qty, cost=data.cost,
                created_by=actor.id, updated_by=actor.id,
            )
            await self.products.add_purchase(purchase)
            product.stock = (product.stock or 0) + data.qty
        product.updated_by = actor.id
        # The new/updated row went in through a separate object, not through
        # product.purchase_history itself, so that already-loaded collection
        # is now stale in the session's identity map — expire it so
        # get_product() below actually re-reads it.
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
        await self.products.lock_for_update(product_id)
        product = await self.get_product(product_id)
        purchase = next((p for p in product.purchase_history if p.id == purchase_id), None)
        if purchase is None:
            raise NotFoundError("Purchase record not found.")
        updates = data.model_dump(exclude_unset=True)
        # Same protection delete_purchase already has, applied to an edit
        # instead of a removal: a saved Pump 2 oil row copies this batch's
        # CURRENT cost into its own stock_rate at save time, so changing the
        # cost out from under it would leave that already-finalized sale
        # referencing a rate that no longer exists anywhere in purchase
        # history — just as broken as deleting the batch outright, and until
        # now completely unchecked.
        if "cost" in updates and updates["cost"] != purchase.cost:
            if await self.products.has_final_oil_row_at_rate(product_id, purchase.cost):
                raise ConflictError(
                    f"This purchase (₹{purchase.cost} per {product.unit}) is still used by a saved Pump 2 fuel "
                    "entry's Pocket/Servo oil row — remove or change that oil row's rate on the fuel entry it "
                    "was saved on first, then this purchase's cost can be changed."
                )
        if "qty" in updates and updates["qty"] != purchase.qty:
            delta = updates["qty"] - purchase.qty
            if delta < 0:
                product.stock = await self._guard_qty_reduction(product_id, purchase.cost, updates["qty"], product, delta)
            else:
                product.stock = (product.stock or 0) + delta
        for field, value in updates.items():
            setattr(purchase, field, value)
        if updates:
            purchase.updated_by = actor.id
            product.updated_by = actor.id
        await self.session.flush()
        self.session.expire(product, ["purchase_history"])
        return await self.get_product(product_id)

    # Same stock-delta safety as update_purchase above, applied as a full
    # removal (delta = -qty) instead of a partial correction.
    async def delete_purchase(self, product_id: uuid.UUID, purchase_id: uuid.UUID, actor: User) -> LubricantProduct:
        await self.products.lock_for_update(product_id)
        product = await self.get_product(product_id)
        purchase = next((p for p in product.purchase_history if p.id == purchase_id), None)
        if purchase is None:
            raise NotFoundError("Purchase record not found.")
        # A saved Pump 2 oil row (Pocket/Servo oil) picks its Rate from this
        # exact batch's cost and copies that number in at save time — it's
        # the only place this purchase batch is ever actually referenced
        # from. Deleting it out from under that sale would leave the sale's
        # own Rate pointing at a batch that no longer exists anywhere, with
        # no way back to what it actually cost. Checked before the
        # stock-negative guard below since this is the more specific,
        # more actionable reason to block the delete.
        if await self.products.has_final_oil_row_at_rate(product_id, purchase.cost):
            raise ConflictError(
                f"This purchase (₹{purchase.cost} per {product.unit}) is still used by a saved Pump 2 fuel "
                "entry's Pocket/Servo oil row — remove or change that oil row's rate on the fuel entry it "
                "was saved on first, then this purchase can be deleted."
            )
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

    async def get_sales_history(self, product_id: uuid.UUID, offset: int = 0, limit: int = 500) -> list[dict]:
        await self.get_product(product_id)  # 404s if the product doesn't exist
        rows = await self.products.get_sales_history(product_id, offset=offset, limit=limit)
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
