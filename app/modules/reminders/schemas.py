"""Schemas de recordatorios (contrato público del módulo)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.reminders.models import ReminderChannel, ReminderStatus, ReminderType


class ReminderInfo(BaseModel):
    """Vista serializable de un recordatorio."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reservation_id: uuid.UUID
    type: ReminderType
    status: ReminderStatus
    scheduled_send_at: datetime
    sent_at: datetime | None = None
    attempts: int = 0
    channel: ReminderChannel
