"""One-off bootstrap: load the Lubricant_Products table with the same seed
data the frontend used to carry as local mock data
(ui/src/data/mockData.js LUBRICANT_PRODUCTS), now that the Lubricants page
reads from this API instead. Safe to re-run — it skips any product whose
name already exists.

    python -m scripts.seed_lubricants
"""

import asyncio
from datetime import date, timedelta

from app.core.database import AsyncSessionLocal
from app.models.lubricant import LubricantPriceHistory, LubricantProduct, LubricantPurchaseHistory
from app.repositories.lubricant_repository import LubricantRepository


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)


# (name, packaging, stock, [(days_ago, rate), ...], [(days_ago, qty, cost), ...])
SEED_PRODUCTS = [
    ("Servo 2T Oil (1L)", "packet", 24, [(60, "300"), (20, "320")], [(9, 30, "260")]),
    ("Servo 4T Eco (1L)", "packet", 18, [(60, "380")], [(11, 25, "310")]),
    ("Servo System 20L (Bucket)", "cane", 4, [(60, "3450")], [(14, 5, "2900")]),
    ("Servo HS Density (1L)", "packet", 12, [(60, "410")], [(8, 15, "340")]),
    ("Servo Prime 20W40 (1L)", "packet", 16, [(60, "360")], [(10, 20, "300")]),
    ("Servo Diesel Additive", "packet", 9, [(60, "250")], [(7, 12, "205")]),
    ("Coolant Top-Up (1L)", "packet", 14, [(60, "220")], [(6, 18, "180")]),
    ("Brake Fluid DOT 3 (500ml)", "packet", 7, [(60, "180")], [(12, 10, "145")]),
    ("Chain Lube Spray", "packet", 6, [(60, "260")], [(9, 8, "210")]),
    ("Servo Gear Oil 90 (1L)", "packet", 11, [(60, "340")], [(13, 14, "285")]),
    ("Air Filter (Two Wheeler)", "packet", 10, [(60, "150")], [(5, 12, "120")]),
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        repo = LubricantRepository(session)
        existing = await repo.list_with_history(limit=200)
        existing_names = {p.name for p in existing}

        created = 0
        for name, packaging, stock, price_history, purchase_history in SEED_PRODUCTS:
            if name in existing_names:
                print(f"Skipping (already exists): {name}")
                continue

            product = LubricantProduct(name=name, unit="Pcs", packaging=packaging, stock=stock)
            product.price_history = [
                LubricantPriceHistory(effective_from=days_ago(offset), rate=rate)
                for offset, rate in price_history
            ]
            product.purchase_history = [
                LubricantPurchaseHistory(date=days_ago(offset), qty=qty, cost=cost)
                for offset, qty, cost in purchase_history
            ]
            await repo.create(product)
            print(f"Created: {name} ({product.id})")
            created += 1

        await session.commit()
        print(f"Done — {created} product(s) created, {len(existing_names)} already present.")


if __name__ == "__main__":
    asyncio.run(seed())
