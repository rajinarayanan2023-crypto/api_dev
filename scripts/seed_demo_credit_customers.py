"""One-off: seed the real Credit_Customers table with the same 17 demo
customers the UI's mock data (ui/src/data/mockData.js CREDIT_CUSTOMERS) has
always shipped with.

Credit Bills CRUD (ledger entries, bill uploads, edit/delete) is deferred to
a future session, so this only seeds the bare customer identity fields
(name, phone, opening_balance) needed to unblock the Offers module, which
sends to Credit_Customers rows by real id. The Offers frontend maps each
mock customer to a real backend customer by NAME, same pattern as
seed_demo_employees.py / Attendance.

Idempotent: skips any name that already exists, so it's safe to run again.

    python -m scripts.seed_demo_credit_customers
"""

import asyncio
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.models.credit import CreditCustomer
from app.repositories.credit_customer_repository import CreditCustomerRepository

DEMO_CUSTOMERS = [
    {"name": "Murugan Transports", "phone": "9894410011", "opening_balance": "42500"},
    {"name": "SRM Lorries", "phone": "9894410012", "opening_balance": "68200"},
    {"name": "Nadar Higher Secondary School", "phone": "9894410013", "opening_balance": "8600"},
    {"name": "Palani Bus Service", "phone": "9894410014", "opening_balance": "21400"},
    {"name": "Vairavan Agro Traders", "phone": "9894410015", "opening_balance": "0"},
    {"name": "Kamaraj Lorry Owners", "phone": "9894410016", "opening_balance": "55300"},
    {"name": "Puliyangudi Municipality", "phone": "9894410017", "opening_balance": "14200"},
    {"name": "Sankaralinga Transports", "phone": "9894410018", "opening_balance": "31800"},
    {"name": "Alagappa Rice Mill", "phone": "9894410019", "opening_balance": "0"},
    {"name": "Nellai Borewell Services", "phone": "9894410020", "opening_balance": "9700"},
    {"name": "Sri Ranga Poultry Farm", "phone": "9894410021", "opening_balance": "4200"},
    {"name": "Meenakshi Travels", "phone": "9894410022", "opening_balance": "18900"},
    {"name": "Kovilpatti Cotton Mills", "phone": "9894410023", "opening_balance": "76500"},
    {"name": "Sivan Textiles", "phone": "9894410024", "opening_balance": "0"},
    {"name": "Amman Flour Mill", "phone": "9894410025", "opening_balance": "6300"},
    {"name": "Tenkasi RTO Fleet", "phone": "9894410026", "opening_balance": "12800"},
    {"name": "Sengunthar Weavers Co-op", "phone": "9894410027", "opening_balance": "3100"},
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        repo = CreditCustomerRepository(session)
        existing = await repo.list(limit=1000)
        existing_names = {c.name for c in existing}

        created = []
        for data in DEMO_CUSTOMERS:
            if data["name"] in existing_names:
                print(f"skip (already exists): {data['name']}")
                continue

            customer = CreditCustomer(
                name=data["name"],
                phone=data["phone"],
                opening_balance=Decimal(data["opening_balance"]),
            )
            await repo.create(customer)
            created.append((data["name"], str(customer.id)))

        await session.commit()

        print(f"\n{len(created)} customer(s) created:")
        for name, cust_id in created:
            print(f"  {name}: {cust_id}")


if __name__ == "__main__":
    asyncio.run(seed())
