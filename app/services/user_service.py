import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import PasswordChange, UserCreate, UserUpdate


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    async def create_user(self, data: UserCreate, actor: User) -> User:
        existing = await self.users.get_by_email(data.email)
        if existing is not None:
            raise ConflictError("A user with this email already exists.")

        user = User(
            email=data.email.lower(),
            name=data.name,
            role=data.role.value,
            phone=data.phone,
            password_hash=hash_password(data.password),
        )
        created = await self.users.create(user)
        return created

    async def list_users(self, offset: int = 0, limit: int = 100) -> list[User]:
        return await self.users.list(offset=offset, limit=limit)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    async def update_user(self, user_id: uuid.UUID, data: UserUpdate, actor: User) -> User:
        user = await self.get_user(user_id)
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            if field == "role":
                value = value.value if hasattr(value, "value") else value
            setattr(user, field, value)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def change_password(self, user: User, data: PasswordChange) -> None:
        if not verify_password(data.current_password, user.password_hash):
            raise UnauthorizedError("Current password is incorrect.")
        user.password_hash = hash_password(data.new_password)
        await self.session.flush()
        # Changing the password invalidates every existing session so a
        # leaked/expired session can't keep using the old credential window.
        await self.refresh_tokens.revoke_all_for_user(user.id)

    async def deactivate_user(self, user_id: uuid.UUID, actor: User) -> None:
        user = await self.get_user(user_id)
        user.active = False
        await self.session.flush()
        await self.refresh_tokens.revoke_all_for_user(user.id)
