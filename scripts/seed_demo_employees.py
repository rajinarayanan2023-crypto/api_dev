"""One-off: seed the real Employees table with the same 7 demo employees the
UI's mock data (ui/src/data/mockData.js EMPLOYEES) has always shipped with.

The Attendance page's employee list still comes from that mock array (its
ids like "e1" aren't real UUIDs), so the frontend maps each mock employee to
a real backend employee by NAME (see ui/src/lib/attendanceApi.js) rather than
by id. This script is what gives that name-match something to find.

Idempotent: skips any name that already exists, so it's safe to run again
after adding more via the UI's Employees page.

    python -m scripts.seed_demo_employees
"""

import asyncio
from datetime import date
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.models.employee import Employee, EmployeeSalaryHistory
from app.repositories.employee_repository import EmployeeRepository

DEMO_EMPLOYEES = [
    {
        "name": "Murugan S",
        "father_name": "Shanmugam",
        "role": "Pump Operator",
        "phone": "9843211001",
        "join_date": "2021-03-14",
        "active": True,
        "notes": "Reliable morning-shift operator, good with customers.",
        "salary_history": [("2021-03-14", "12000"), ("2023-04-01", "15000")],
    },
    {
        "name": "Karthikeyan R",
        "father_name": "Ramasamy",
        "role": "Pump Operator",
        "phone": "9843211002",
        "join_date": "2021-06-02",
        "active": True,
        "notes": "",
        "salary_history": [("2021-06-02", "15000")],
    },
    {
        "name": "Lakshmi Priya",
        "father_name": "Duraisamy",
        "role": "Cashier",
        "phone": "9843211003",
        "join_date": "2022-01-19",
        "active": True,
        "notes": "Handles cash reconciliation independently.",
        "salary_history": [("2022-01-19", "16000")],
    },
    {
        "name": "Selvam Nadar",
        "father_name": "Kaliyaperumal Nadar",
        "role": "Supervisor",
        "phone": "9843211004",
        "join_date": "2019-11-05",
        "active": True,
        "notes": "Senior staff, oversees shift handovers.",
        "salary_history": [("2019-11-05", "18000"), ("2022-04-01", "22000")],
    },
    {
        "name": "Meena K",
        "father_name": "Krishnan",
        "role": "Attendant",
        "phone": "9843211005",
        "join_date": "2023-02-27",
        "active": True,
        "notes": "",
        "salary_history": [("2023-02-27", "12000")],
    },
    {
        "name": "Rajesh Kumar",
        "father_name": "Govindasamy",
        "role": "Night Operator",
        "phone": "9843211006",
        "join_date": "2022-08-11",
        "active": True,
        "notes": "Often does a double (24hr) shift, then takes the next day off.",
        "salary_history": [("2022-08-11", "15000")],
    },
    {
        "name": "Suresh Babu",
        "father_name": "Marimuthu",
        "role": "Cleaner",
        "phone": "9843211007",
        "join_date": "2023-07-09",
        "active": True,
        "notes": "",
        "salary_history": [("2023-07-09", "10000")],
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        repo = EmployeeRepository(session)
        existing = await repo.list(limit=1000)
        existing_names = {e.name for e in existing}

        created = []
        for data in DEMO_EMPLOYEES:
            if data["name"] in existing_names:
                print(f"skip (already exists): {data['name']}")
                continue

            employee = Employee(
                name=data["name"],
                father_name=data["father_name"],
                role=data["role"],
                phone=data["phone"],
                join_date=date.fromisoformat(data["join_date"]),
                active=data["active"],
                notes=data["notes"],
            )
            employee.salary_history = [
                EmployeeSalaryHistory(effective_from=date.fromisoformat(eff), amount=Decimal(amt))
                for eff, amt in data["salary_history"]
            ]
            await repo.create(employee)
            created.append((data["name"], str(employee.id)))

        await session.commit()

        print(f"\n{len(created)} employee(s) created:")
        for name, emp_id in created:
            print(f"  {name}: {emp_id}")


if __name__ == "__main__":
    asyncio.run(seed())
