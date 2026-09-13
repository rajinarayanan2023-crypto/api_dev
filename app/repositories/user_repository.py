from sqlalchemy import or_, select
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
        """Login lookup: matches the email case-insensitively (emails are
        always stored lowercased — see get_by_email/create — and treating
        them case-insensitively at login is the universal convention, not a
        security gap), but matches the display name EXACTLY as stored. A
        name is a login credential like the password right next to it, not
        a search field to be matched loosely — "dev" and "DEV" must be
        different accounts if that's genuinely how two users are named.
        Only surrounding whitespace is trimmed from either side. Unlike
        email, name isn't unique — .first() rather than .scalar_one_or_none()
        so two staff sharing a display name can't turn a login attempt into
        a server error.
        """
        stripped = identifier.strip()
        result = await self.session.execute(
            select(User).where(or_(User.email == stripped.lower(), User.name == stripped))
        )
        return result.scalars().first()
