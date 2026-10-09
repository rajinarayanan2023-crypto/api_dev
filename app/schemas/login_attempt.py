import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class LoginAttemptOut(ORMModel):
    id: uuid.UUID
    identifier: str
    user_id: uuid.UUID | None = None
    action: str
    success: bool
    reason: str | None = None
    ip_address: str | None = None
    created_at: datetime
