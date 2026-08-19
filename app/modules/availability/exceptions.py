"""Excepciones del modulo de disponibilidad."""

from app.core.exceptions import AppError
from app.modules.availability.schemas import AvailabilityReason, TableInfo


class AvailabilityError(AppError):
    """Error base del modulo de disponibilidad."""


class NoAvailabilityError(AvailabilityError):
    """No hay forma de atender la peticion (cerrado, aforo, sin mesa, fuera de horario).

    Lleva el `reason` (motivo de `AvailabilityReason`) y las alternativas libres
    que quepan, para que el caller pueda ofrecerlas al cliente.
    """

    def __init__(
        self,
        reason: AvailabilityReason,
        *,
        alternatives: list[TableInfo] | None = None,
    ) -> None:
        self.reason = reason
        self.alternatives = alternatives or []
        super().__init__(f"No hay disponibilidad: {reason.value}", data={"reason": reason.value})
