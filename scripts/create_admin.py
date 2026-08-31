"""One-off bootstrap: create the first admin user directly in the DB.

Every other account is created through POST /api/v1/users, which requires an
admin caller — so the very first admin has to be seeded out-of-band. Run
after migrations are applied:

    python -m scripts.create_admin --email you@example.com --name "Your Name"

You'll be prompted for a password (not taken as a CLI arg, so it never ends
up in shell history).
"""

import argparse
import asyncio
import getpass
import sys

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import validate_password_strength


async def create_admin(email: str, full_name: str, password: str) -> None:
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(email)
        if existing is not None:
            print(f"A user with email {email} already exists.", file=sys.stderr)
            raise SystemExit(1)

        user = User(
            email=email.lower(),
            name=full_name,
            role=UserRole.ADMIN.value,
            password_hash=hash_password(password),
        )
        await repo.create(user)
        await session.commit()
        print(f"Admin user created: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the first admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, dest="full_name")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)

    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(f"Weak password: {exc}", file=sys.stderr)
        raise SystemExit(1)

    asyncio.run(create_admin(args.email, args.full_name, password))


if __name__ == "__main__":
    main()
