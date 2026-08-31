import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_admin
from app.models.user import User
from app.schemas.common import Message
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_admin),
) -> UserOut:
    service = UserService(session)
    user = await service.create_user(body, current_user)
    return UserOut.model_validate(user)


@router.get("", response_model=list[UserOut])
async def list_users(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserOut]:
    service = UserService(session)
    users = await service.list_users(offset=offset, limit=limit)
    return [UserOut.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> UserOut:
    service = UserService(session)
    user = await service.get_user(user_id)
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_admin),
) -> UserOut:
    service = UserService(session)
    user = await service.update_user(user_id, body, current_user)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", response_model=Message)
async def deactivate_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_admin),
) -> Message:
    service = UserService(session)
    await service.deactivate_user(user_id, current_user)
    return Message(detail="User deactivated.")
