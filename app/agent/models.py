"""Modelos de metadatos de conversacion del agente (orquestador).

No son dominio del restaurante: viven en `app/agent/` porque describen la
interaccion con el LLM (conversaciones y escalaciones).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_check, enum_values


class ConversationChannel(StrEnum):
    WHATSAPP = "whatsapp"
    VOICE = "voice"


class ConversationOutcome(StrEnum):
    RESERVATION_CREATED = "reservation_created"
    QUERY = "query"
    COMPLAINT = "complaint"
    ESCALATED = "escalated"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Conversacion mantenida con un cliente a traves de un canal."""

    __tablename__ = "conversations"
    __table_args__ = (
        enum_check("channel", ConversationChannel, name="conversation_channel"),
        enum_check("outcome", ConversationOutcome, name="conversation_outcome"),
        Index("ix_conversations_restaurant_id_date", "restaurant_id", "date"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        Enum(
            ConversationChannel,
            name="conversation_channel",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[ConversationOutcome | None] = mapped_column(
        Enum(
            ConversationOutcome,
            name="conversation_outcome",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EscalationReason(StrEnum):
    """Motivos de escalacion (derivados de los flujos de las secciones 9 y 10).

    `technical_failure` es la traduccion de `fallo_tecnico` del glosario.
    """

    LARGE_GROUP = "large_group"
    COMPLAINT = "complaint"
    TECHNICAL_FAILURE = "technical_failure"
    CLARIFICATION_FAILED = "clarification_failed"
    VOICE_TRANSFER_FAILED = "voice_transfer_failed"


class EscalationStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"


class Escalation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Escalacion a un humano, asociada a una conversacion."""

    __tablename__ = "escalations"
    __table_args__ = (
        enum_check("reason", EscalationReason, name="escalation_reason"),
        enum_check("status", EscalationStatus, name="escalation_status"),
        Index("ix_escalations_restaurant_id_status", "restaurant_id", "status"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[EscalationReason] = mapped_column(
        Enum(
            EscalationReason,
            name="escalation_reason",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[EscalationStatus] = mapped_column(
        Enum(
            EscalationStatus,
            name="escalation_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
