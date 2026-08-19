"""Modelo de reservas (`reservations`) y sus enums."""

import uuid
from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    Time,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_check, enum_values
from app.modules.availability.models import TableZone


class ReservationStatus(StrEnum):
    PENDING = "pending"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    MODIFIED = "modified"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class SourceChannel(StrEnum):
    WHATSAPP = "whatsapp"
    VOICE = "voice"
    WEB = "web"


class AssignmentReason(StrEnum):
    SPECIFIC_REQUEST = "specific_request"
    HABITUAL_TABLE = "habitual_table"
    STANDARD_AVAILABILITY = "standard_availability"


#: Estados que ocupan mesa: bloquean el hueco mientras sigan activos.
ACTIVE_RESERVATION_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.PENDING,
        ReservationStatus.PENDING_CONFIRMATION,
        ReservationStatus.CONFIRMED,
        ReservationStatus.MODIFIED,
    }
)


class Reservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reserva de una mesa para un cliente en una fecha y hora."""

    __tablename__ = "reservations"
    __table_args__ = (
        enum_check("preferred_zone", TableZone, name="reservation_preferred_zone"),
        enum_check("status", ReservationStatus, name="reservation_status"),
        enum_check("source_channel", SourceChannel, name="source_channel"),
        enum_check("assignment_reason", AssignmentReason, name="assignment_reason"),
        Index("ix_reservations_restaurant_id_date", "restaurant_id", "date"),
        Index("ix_reservations_restaurant_id_status_date", "restaurant_id", "status", "date"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    time: Mapped[time_type] = mapped_column(Time(timezone=False), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_zone: Mapped[TableZone | None] = mapped_column(
        Enum(
            TableZone,
            name="reservation_preferred_zone",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(
            ReservationStatus,
            name="reservation_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    source_channel: Mapped[SourceChannel] = mapped_column(
        Enum(
            SourceChannel,
            name="source_channel",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignment_reason: Mapped[AssignmentReason | None] = mapped_column(
        Enum(
            AssignmentReason,
            name="assignment_reason",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    has_preorder: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
