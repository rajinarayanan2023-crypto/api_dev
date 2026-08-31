from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_ACTOR_FIELDS = ("created_by", "updated_by")


async def attach_actor_names(session: AsyncSession, objs: Sequence[Any]) -> None:
    """Resolve created_by/updated_by user ids to display names in one batch
    query, setting `<field>_name` as a plain attribute (not a mapped column)
    on each object — the *Out schemas read it via Pydantic's
    `from_attributes`, same as any other field.
    """
    ids = {getattr(obj, field) for obj in objs for field in _ACTOR_FIELDS if getattr(obj, field, None) is not None}
    names: dict[Any, str] = {}
    if ids:
        result = await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
        names = dict(result.all())
    for obj in objs:
        for field in _ACTOR_FIELDS:
            setattr(obj, f"{field}_name", names.get(getattr(obj, field, None)))
