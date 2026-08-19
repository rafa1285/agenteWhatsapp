"""Schemas de clientes (contrato público del módulo).

`CustomerInfo` es la vista serializable de la entidad `Customer` usada en los
endpoints REST y las tools del LLM.
"""

import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class CustomerInfo(BaseModel):
    """Vista serializable de un cliente."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    phone: str
    name: str | None = None
    allergies: str | None = None
    preferences: str | None = None
    preferred_table_id: uuid.UUID | None = None
    preferred_language: str | None = "es"
    visit_count: int = 0
    last_visit: datetime | None = None
    no_show_count: int = 0
    requires_prior_confirmation: bool = False
    last_complaint_date: date_type | None = None
    estimated_average_ticket: Decimal | None = None
    last_order: Any | None = None
