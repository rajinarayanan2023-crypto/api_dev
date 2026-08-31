from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Login lookup: matches either the email or the display name,
        case-insensitively, so a user can sign in with whichever they
        remember. Unlike email, name isn't unique — .first() rather than
        .scalar_one_or_none() so two staff sharing a display name can't
        turn a login attempt into a server error.
        """
        normalized = identifier.strip().lower()
        result = await self.session.execute(
            select(User).where(or_(User.email == normalized, func.lower(User.name) == normalized))
        )
        return result.scalars().first()
