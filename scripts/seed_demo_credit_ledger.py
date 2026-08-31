"""One-off: seed the real Credit_Ledger_Entries table with the same demo
transaction history the UI's mock data (ui/src/data/mockData.js
CREDIT_CUSTOMERS[*].ledger) has always shipped with, against the 17 real
Credit_Customers rows already seeded by seed_demo_credit_customers.py.

Idempotent: skips any customer that already has at least one ledger entry
(so it's safe to run again after the Credit Bills page has real activity).

    python -m scripts.seed_demo_credit_ledger
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.models.credit import CreditLedgerEntry
from app.repositories.credit_customer_repository import CreditCustomerRepository


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)


def credit(days: int, fuel_type: str, litres: float, rate: float) -> dict:
    return {
        "date": days_ago(days),
        "type": "credit",
        "fuel_type": fuel_type,
        "litres": Decimal(str(litres)),
        "rate": Decimal(str(rate)),
        "amount": Decimal(round(litres * rate, 2)),
        "mode": None,
    }


def payment(days: int, amount: float, mode: str) -> dict:
    return {
        "date": days_ago(days),
        "type": "payment",
        "fuel_type": None,
        "litres": None,
        "rate": None,
        "amount": Decimal(str(amount)),
        "mode": mode,
    }


DEMO_LEDGER = {
    "Murugan Transports": [credit(6, "diesel", 400, 100.45), credit(3, "diesel", 320, 100.45), payment(1, 20000, "Cash")],
    "SRM Lorries": [credit(7, "diesel", 600, 100.45), credit(4, "diesel", 500, 100.45)],
    "Nadar Higher Secondary School": [credit(5, "diesel", 80, 100.45), payment(2, 8600, "Online")],
    "Palani Bus Service": [credit(6, "diesel", 250, 100.45), credit(2, "diesel", 210, 100.45)],
    "Vairavan Agro Traders": [credit(3, "diesel", 150, 100.45), payment(1, 15068, "Cash")],
    "Kamaraj Lorry Owners": [credit(5, "diesel", 450, 100.45)],
    "Puliyangudi Municipality": [credit(4, "petrol", 60, 108.6), credit(1, "diesel", 90, 100.45)],
    "Sankaralinga Transports": [credit(6, "diesel", 320, 100.45), payment(3, 10000, "Card")],
    "Alagappa Rice Mill": [credit(2, "diesel", 200, 100.45)],
    "Nellai Borewell Services": [credit(5, "diesel", 95, 100.45)],
    "Sri Ranga Poultry Farm": [credit(3, "petrol", 20, 108.6), credit(1, "diesel", 20, 100.45)],
    "Meenakshi Travels": [credit(4, "diesel", 180, 100.45), payment(2, 5000, "Online")],
    "Kovilpatti Cotton Mills": [credit(7, "diesel", 700, 100.45), credit(3, "diesel", 350, 100.45)],
    "Sivan Textiles": [],
    "Amman Flour Mill": [credit(2, "diesel", 60, 100.45)],
    "Tenkasi RTO Fleet": [credit(6, "petrol", 90, 108.6), payment(1, 6000, "Cash")],
    "Sengunthar Weavers Co-op": [],
}


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        repo = CreditCustomerRepository(session)
        customers = await repo.list_with_details(limit=1000)
        by_name = {c.name: c for c in customers}

        created = 0
        for name, rows in DEMO_LEDGER.items():
            customer = by_name.get(name)
            if customer is None:
                print(f"skip (customer not found): {name}")
                continue
            if customer.ledger_entries:
                print(f"skip (already has ledger entries): {name}")
                continue
            for row in rows:
                session.add(CreditLedgerEntry(customer_id=customer.id, **row))
                created += 1

        await session.commit()
        print(f"\n{created} ledger entr{'y' if created == 1 else 'ies'} created.")


if __name__ == "__main__":
    asyncio.run(seed())
