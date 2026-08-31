"""One-off bootstrap: load the Employees table with the same seed data the
frontend used to carry as local mock data (ui/src/data/mockData.js EMPLOYEES),
now that the Employees page reads from this API instead. Safe to re-run — it
skips any employee whose name already exists.

    python -m scripts.seed_employees
"""

import asyncio

from app.core.database import AsyncSessionLocal
from app.models.employee import Employee, EmployeeSalaryHistory
from app.repositories.employee_repository import EmployeeRepository

SEED_EMPLOYEES = [
    {
        "name": "Murugan S", "father_name": "Shanmugam", "role": "Pump Operator", "phone": "9843211001",
        "join_date": "2021-03-14", "active": True,
        "notes": "Reliable morning-shift operator, good with customers.",
        "salary_history": [("2021-03-14", "12000"), ("2023-04-01", "15000")],
    },
    {
        "name": "Karthikeyan R", "father_name": "Ramasamy", "role": "Pump Operator", "phone": "9843211002",
        "join_date": "2021-06-02", "active": True, "notes": "",
        "salary_history": [("2021-06-02", "15000")],
    },
    {
        "name": "Lakshmi Priya", "father_name": "Duraisamy", "role": "Cashier", "phone": "9843211003",
        "join_date": "2022-01-19", "active": True,
        "notes": "Handles cash reconciliation independently.",
        "salary_history": [("2022-01-19", "16000")],
    },
    {
        "name": "Selvam Nadar", "father_name": "Kaliyaperumal Nadar", "role": "Supervisor", "phone": "9843211004",
        "join_date": "2019-11-05", "active": True,
        "notes": "Senior staff, oversees shift handovers.",
        "salary_history": [("2019-11-05", "18000"), ("2022-04-01", "22000")],
    },
    {
        "name": "Meena K", "father_name": "Krishnan", "role": "Attendant", "phone": "9843211005",
        "join_date": "2023-02-27", "active": True, "notes": "",
        "salary_history": [("2023-02-27", "12000")],
    },
    {
        "name": "Rajesh Kumar", "father_name": "Govindasamy", "role": "Night Operator", "phone": "9843211006",
        "join_date": "2022-08-11", "active": True,
        "notes": "Often does a double (24hr) shift, then takes the next day off.",
        "salary_history": [("2022-08-11", "15000")],
    },
    {
        "name": "Suresh Babu", "father_name": "Marimuthu", "role": "Cleaner", "phone": "9843211007",
        "join_date": "2023-07-09", "active": True, "notes": "",
        "salary_history": [("2023-07-09", "10000")],
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        repo = EmployeeRepository(session)
        existing = await repo.list_with_salary_history(limit=200)
        existing_names = {e.name for e in existing}

        created = 0
        for data in SEED_EMPLOYEES:
            if data["name"] in existing_names:
                print(f"Skipping (already exists): {data['name']}")
                continue

            employee = Employee(
                name=data["name"],
                father_name=data["father_name"],
                role=data["role"],
                phone=data["phone"],
                join_date=data["join_date"],
                active=data["active"],
                notes=data["notes"],
            )
            employee.salary_history = [
                EmployeeSalaryHistory(effective_from=effective_from, amount=amount)
                for effective_from, amount in data["salary_history"]
            ]
            await repo.create(employee)
            print(f"Created: {data['name']} ({employee.id})")
            created += 1

        await session.commit()
        print(f"Done — {created} employee(s) created, {len(existing_names)} already present.")


if __name__ == "__main__":
    asyncio.run(seed())
