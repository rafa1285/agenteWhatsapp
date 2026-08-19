"""Modelo de recordatorios (`reminders`)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_check, enum_values


class ReminderType(StrEnum):
    REMINDER_24H = "24h_reminder"
    MANDATORY_CONFIRMATION = "mandatory_confirmation"
    RELEASE_NOTICE = "release_notice"
    POST_VISIT = "post_visit"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReminderChannel(StrEnum):
    WHATSAPP = "whatsapp"
    SMS = "sms"


class Reminder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Recordatorio programado asociado a una reserva."""

    __tablename__ = "reminders"
    __table_args__ = (
        enum_check("type", ReminderType, name="reminder_type"),
        enum_check("status", ReminderStatus, name="reminder_status"),
        enum_check("channel", ReminderChannel, name="reminder_channel"),
        Index("ix_reminders_status_scheduled_send_at", "status", "scheduled_send_at"),
    )

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ReminderType] = mapped_column(
        Enum(
            ReminderType,
            name="reminder_type",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(
            ReminderStatus,
            name="reminder_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    scheduled_send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    channel: Mapped[ReminderChannel] = mapped_column(
        Enum(
            ReminderChannel,
            name="reminder_channel",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        server_default=text("'whatsapp'"),
    )
