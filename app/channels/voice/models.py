"""Modelo de registro del canal de voz (capa de transporte).

`voice_calls` es a la vez la fila de dedup por `call_sid` (unique, evita dobles
por carrera en el webhook de Twilio) y el acumulador de estado de la llamada
(silencios, confirmación escrita, grabación, status). No es dominio del
restaurante: describe una llamada telefónica atendida por el agente.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_check, enum_values


class VoiceCallStatus(StrEnum):
    """Estados del ciclo de vida de una llamada de voz."""

    IN_PROGRESS = "in_progress"
    INCOMPLETE = "incomplete"
    COMPLETED = "completed"
    TRANSFERRED = "transferred"


class VoiceCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Llamada de voz entrante atendida por el agente (dedup + estado)."""

    __tablename__ = "voice_calls"
    __table_args__ = (
        UniqueConstraint("call_sid", name="uq_voice_calls_call_sid"),
        enum_check("status", VoiceCallStatus, name="voice_call_status"),
    )

    call_sid: Mapped[str] = mapped_column(String(64), nullable=False)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[VoiceCallStatus] = mapped_column(
        Enum(
            VoiceCallStatus,
            name="voice_call_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        server_default=text("'in_progress'"),
    )
    silence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confirmation_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    call_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
