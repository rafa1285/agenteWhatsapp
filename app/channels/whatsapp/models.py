"""Modelo de dedup del webhook de WhatsApp (capa de transporte).

No es dominio del restaurante: registra qué mensajes entrantes de la API de
WhatsApp ya se procesaron, para no reaccionar a reentregas de 360dialog. La
unicidad por `(restaurant_id, wa_message_id)` garantiza "at-most-once".
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mensaje entrante de WhatsApp ya atendido (marca de dedup)."""

    __tablename__ = "webhook_messages"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "wa_message_id", name="uq_webhook_messages_restaurant_wa_message"
        ),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wa_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
