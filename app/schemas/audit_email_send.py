import uuid
from datetime import date, datetime

from app.schemas.common import ORMModel


class AuditEmailSendOut(ORMModel):
    id: uuid.UUID
    date: date
    is_shift3: bool
    recipient_email: str
    sent_at: datetime
    created_by_name: str | None = None
