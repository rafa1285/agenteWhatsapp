"""Schemas de reservas (contrato de entrada para routers y tools del LLM).

El `restaurant_id` no forma parte de los inputs: llega del contexto del tenant
(auth JWT en los routers, el restaurante de la conversacion en el agente).
"""

import uuid
from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type

from pydantic import BaseModel, ConfigDict, Field

from app.modules.availability.models import TableZone
from app.modules.reservations.models import SourceChannel


class ReservationCreateInput(BaseModel):
    """Cuerpo para crear una reserva."""

    customer_id: uuid.UUID
    date: date_type
    time: time_type
    party_size: int = Field(gt=0)
    source_channel: SourceChannel
    preferred_zone: TableZone | None = None
    requested_table_id: uuid.UUID | None = None
    notes: str | None = None


class ReservationModifyInput(BaseModel):
    """Cuerpo para modificar una reserva (todos los campos opcionales)."""

    date: date_type | None = None
    time: time_type | None = None
    party_size: int | None = Field(default=None, gt=0)
    preferred_zone: TableZone | None = None
    requested_table_id: uuid.UUID | None = None
    notes: str | None = None


class BookingInput(BaseModel):
    """Args que el LLM puede emitir para crear una reserva.

    Sin `customer_id`/`source_channel`/`restaurant_id`: vienen del contexto de
    la conversación (ToolContext). `requested_table_id` tampoco se expone: la
    asignación de mesa es responsabilidad del motor.
    """

    date: date_type
    time: time_type
    party_size: int = Field(gt=0)
    preferred_zone: TableZone | None = None
    notes: str | None = None


class BookingModifyInput(BaseModel):
    """Args LLM para modificar la reserva activa (todos opcionales).

    `reservation_id` viene del contexto; no se exponen UUIDs de mesa.
    """

    date: date_type | None = None
    time: time_type | None = None
    party_size: int | None = Field(default=None, gt=0)
    preferred_zone: TableZone | None = None
    notes: str | None = None


class CancelBookingInput(BaseModel):
    """Cancelación de la reserva activa.

    Requiere `confirmed=true` (§9: el agente nunca cancela sin confirmación
    explícita del cliente).
    """

    confirmed: bool
    reason: str | None = None


class ReservationInfo(BaseModel):
    """Respuesta estándar de una reserva (para webhooks y listados)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    table_id: uuid.UUID | None = None
    date: date_type
    time: time_type
    party_size: int
    status: str
    source_channel: str
    preferred_zone: str | None = None
    notes: str | None = None
    assignment_reason: str | None = None
    checked_in_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
