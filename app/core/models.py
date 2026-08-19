"""Modelos de tenant y configuracion del restaurante (capa core).

`Restaurant` es la configuracion que identifica a cada tenant: no es un modulo
de dominio de negocio (mesas, reservas, clientes...), por eso vive aqui y no en
`app/modules/`. Toda consulta multi-tenant filtra por `restaurant_id`.
"""

from datetime import time as time_type
from typing import Any

from sqlalchemy import Boolean, Integer, String, Text, Time, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Restaurant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configuracion de un restaurante (tenant)."""

    __tablename__ = "restaurants"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    public_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    whatsapp_number_id: Mapped[str] = mapped_column(String(64), nullable=False)
    voice_number: Mapped[str] = mapped_column(String(32), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Europe/Madrid'")
    )
    opening_time: Mapped[time_type | None] = mapped_column(Time(timezone=False), nullable=True)
    closing_time: Mapped[time_type | None] = mapped_column(Time(timezone=False), nullable=True)
    prompt_tone: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    no_show_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2")
    )
    auto_confirm_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    supported_languages: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[\"es\"]'::jsonb")
    )
    large_group_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("8")
    )
    live_transfer_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    transfer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transfer_hours: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    confirmation_deadline: Mapped[time_type | None] = mapped_column(
        Time(timezone=False), nullable=True
    )
    preorder_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
