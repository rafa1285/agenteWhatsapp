"""Modelos de disponibilidad: mesas (`tables`) y turnos (`shifts`)."""

import uuid
from datetime import date as date_type
from datetime import time as time_type
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_check, enum_values


class TableZone(StrEnum):
    """Zonas fisicas de una mesa (glosario: salon/terraza/barra)."""

    INDOOR = "indoor"
    TERRACE = "terrace"
    BAR = "bar"


class Table(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mesa del plano del restaurante."""

    __tablename__ = "tables"
    __table_args__ = (enum_check("zone", TableZone, name="table_zone"),)

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    zone: Mapped[TableZone] = mapped_column(
        Enum(
            TableZone,
            name="table_zone",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    min_capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    max_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    position_x: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    position_y: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)


class Shift(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Turno de servicio: un dia de la semana o una fecha especial."""

    __tablename__ = "shifts"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 0=lunes ... 6=domingo (ISO); se usa junto a `special_date` (uno de los dos).
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    special_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time_type] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[time_type] = mapped_column(Time(timezone=False), nullable=False)
    average_table_duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("90"),  # minutos
    )
    max_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
