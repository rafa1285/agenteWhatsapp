"""Schemas de disponibilidad (contrato publico del modulo).

`AvailabilityResult` es lo que devuelve `check_availability`; los routers y
las tools del LLM lo serializan tal cual. `TableInfo`/`ShiftInfo` son vistas
serializables de las entidades `Table` y `Shift`.
"""

import uuid
from datetime import date as date_type
from datetime import time as time_type
from enum import StrEnum

from pydantic import BaseModel, Field

from app.modules.availability.models import TableZone


class AvailabilityReason(StrEnum):
    """Motivo por el que una peticion no se puede atender (o si se puede)."""

    AVAILABLE = "available"
    CLOSED = "closed"
    OUTSIDE_SERVICE_HOURS = "outside_service_hours"
    AFORO_EXCEEDED = "aforo_exceeded"
    NO_TABLE_FOR_PARTY = "no_table_for_party"


class TableInfo(BaseModel):
    """Vista serializable de una mesa (sin la configuracion grafica)."""

    id: uuid.UUID
    name: str
    zone: TableZone
    min_capacity: int
    max_capacity: int


class ShiftInfo(BaseModel):
    """Vista serializable del turno activo para la fecha/hora pedida."""

    date: date_type
    start_time: time_type
    end_time: time_type
    duration_minutes: int
    max_capacity: int


class AvailabilityResult(BaseModel):
    """Resultado de `check_availability`: nunca lanza, siempre devuelve un motivo."""

    available: bool
    reason: AvailabilityReason
    preferred_unavailable: bool = False
    shift: ShiftInfo | None = None
    free_tables: list[TableInfo] = Field(default_factory=list)


class CheckAvailabilityInput(BaseModel):
    """Args que el LLM puede emitir para consultar disponibilidad.

    Sin `restaurant_id`: llega del contexto del tenant (ToolContext).
    """

    date: date_type
    time: time_type
    party_size: int = Field(gt=0)
    preferred_zone: TableZone | None = None
