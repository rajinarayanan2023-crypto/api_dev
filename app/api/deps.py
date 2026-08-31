import uuid
from typing import Callable

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import TokenType, decode_token
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

# tokenUrl is only used to populate OpenAPI's "Authorize" button; the actual
# login endpoint takes JSON, not a form-encoded body.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)

get_db_session = get_db


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    invalid = UnauthorizedError("Could not validate credentials.")
    if token is None:
        raise invalid

    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise invalid

    if payload.get("type") != TokenType.ACCESS.value:
        raise invalid

    user_id = payload.get("sub")
    if user_id is None:
        raise invalid

    user = await UserRepository(session).get(uuid.UUID(user_id))
    if user is None or not user.active:
        raise invalid

    return user


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    return user


def require_roles(*roles: UserRole) -> Callable:
    async def _checker(user: User = Depends(get_current_active_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to perform this action.")
        return user

    return _checker


require_admin = require_roles(UserRole.ADMIN)
require_manager_or_admin = require_roles(UserRole.ADMIN, UserRole.MANAGER)
