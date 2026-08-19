"""Excepciones del modulo de reservas.

La API publica de este modulo solo expone errores del dominio de reservas:
`ReservationUnavailableError` traduce el `NoAvailabilityError` del modulo de
disponibilidad (copia `reason` + `alternatives`), de modo que los routers y
tools del LLM no ven excepciones ajenas.
"""

from app.core.exceptions import AppError
from app.modules.availability.schemas import AvailabilityReason, TableInfo


class ReservationError(AppError):
    """Error base del modulo de reservas."""


class ReservationNotFoundError(ReservationError):
    """No existe la reserva para ese `id` + `restaurant_id` (aislamiento multi-tenant)."""


class RestaurantNotFoundError(ReservationError):
    """El restaurante (tenant) indicado no existe."""


class ReservationConflictError(ReservationError):
    """Transicion de estado ilegal, o recurso de otro restaurante."""


class ReservationUnavailableError(ReservationError):
    """La peticion no se puede atender por disponibilidad (motivo + alternativas)."""

    def __init__(
        self,
        reason: AvailabilityReason,
        *,
        alternatives: list[TableInfo] | None = None,
    ) -> None:
        self.reason = reason
        self.alternatives = alternatives or []
        super().__init__(
            f"No hay disponibilidad: {reason.value}",
            data={"reason": reason.value},
        )
