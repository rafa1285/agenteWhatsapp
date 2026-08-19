"""Modelo de clientes del restaurante (`customers`)."""

import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cliente identificado por telefono (clave unica por restaurante)."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "phone", name="uq_customers_restaurant_id_phone"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tables.id", ondelete="SET NULL"), nullable=True
    )
    preferred_language: Mapped[str | None] = mapped_column(
        String(8), nullable=True, server_default=text("'es'")
    )
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_visit: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    no_show_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    requires_prior_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_complaint_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    estimated_average_ticket: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    last_order: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
