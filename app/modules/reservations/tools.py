"""Tools del modulo de reservas (delegan en su `service.py`).

Doble validacion: los args que emite el LLM se validan con los schemas publicos
(`BookingInput`/`BookingModifyInput`/`CancelBookingInput`, sin UUIDs ni canal),
se inyectan los identificadores desde el `ToolContext` y se re-valida con el
contrato del servicio (`ReservationCreateInput`). Nunca lanzan hacia el LLM:
los errores de negocio son dicts con `ok: False`.
"""

from typing import Any

from app.agent.tool import Tool, ToolContext
from app.modules.reservations.exceptions import (
    ReservationConflictError,
    ReservationNotFoundError,
    ReservationUnavailableError,
    RestaurantNotFoundError,
)
from app.modules.reservations.models import Reservation
from app.modules.reservations.schemas import (
    BookingInput,
    BookingModifyInput,
    CancelBookingInput,
    ReservationCreateInput,
)
from app.modules.reservations.service import (
    cancel_reservation,
    create_reservation,
    modify_reservation,
)


def _reservation_to_dict(r: Reservation) -> dict[str, Any]:
    """Vista JSON-serializable de una reserva (para el tool result)."""
    return {
        "id": str(r.id),
        "customer_id": str(r.customer_id) if r.customer_id else None,
        "date": r.date.isoformat(),
        "time": r.time.isoformat(),
        "party_size": r.party_size,
        "status": r.status.value,
        "source_channel": r.source_channel.value,
        "preferred_zone": r.preferred_zone.value if r.preferred_zone else None,
        "table_id": str(r.table_id) if r.table_id else None,
        "assignment_reason": r.assignment_reason.value if r.assignment_reason else None,
        "notes": r.notes,
    }


def _unavailable(exc: ReservationUnavailableError) -> dict[str, Any]:
    """Serializa un error de disponibilidad con su motivo y alternativas libres."""
    return {
        "ok": False,
        "error": "sin_disponibilidad",
        "reason": exc.reason.value,
        "alternatives": [a.model_dump(mode="json") for a in exc.alternatives],
    }


async def create_booking_tool_fn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Crea una reserva para el cliente de la conversacion."""
    if ctx.customer_id is None:
        return {
            "ok": False,
            "error": "customer_desconocido",
            "message": "No tengo identificado al cliente para crear la reserva.",
        }
    public = BookingInput.model_validate(args)
    combined = ReservationCreateInput(
        customer_id=ctx.customer_id,
        date=public.date,
        time=public.time,
        party_size=public.party_size,
        source_channel=ctx.source_channel,
        preferred_zone=public.preferred_zone,
        notes=public.notes,
    )
    try:
        result = await create_reservation(
            ctx.session, restaurant_id=ctx.restaurant_id, **combined.model_dump()
        )
    except ReservationUnavailableError as exc:
        return _unavailable(exc)
    except ReservationConflictError as exc:
        return {"ok": False, "error": "conflicto", "message": str(exc)}
    except RestaurantNotFoundError as exc:
        return {"ok": False, "error": "restaurante_no_encontrado", "message": str(exc)}
    # Senal de escalacion al orquestador (Fase 4): el servicio no crea la fila
    # de Escalation, solo la expone.
    return {
        "ok": True,
        "reservation": _reservation_to_dict(result.reservation),
        "needs_escalation": result.needs_escalation,
        "escalation_reason": (result.escalation_reason.value if result.escalation_reason else None),
        "preferred_unavailable": result.preferred_unavailable,
    }


async def modify_booking_tool_fn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Modifica la reserva activa de la conversacion (solo los campos dados)."""
    if ctx.reservation_id is None:
        return {
            "ok": False,
            "error": "sin_reserva_en_contexto",
            "message": "No hay ninguna reserva activa que modificar.",
        }
    payload = BookingModifyInput.model_validate(args)
    try:
        result = await modify_reservation(
            ctx.session,
            reservation_id=ctx.reservation_id,
            restaurant_id=ctx.restaurant_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ReservationUnavailableError as exc:
        return _unavailable(exc)
    except ReservationNotFoundError as exc:
        return {"ok": False, "error": "reserva_no_encontrada", "message": str(exc)}
    return {
        "ok": True,
        "reservation": _reservation_to_dict(result.reservation),
        "reassigned": result.reassigned,
        "preferred_unavailable": result.preferred_unavailable,
    }


async def cancel_booking_tool_fn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Cancela la reserva activa. Guarda §9: requiere confirmacion explicita."""
    if ctx.reservation_id is None:
        return {
            "ok": False,
            "error": "sin_reserva_en_contexto",
            "message": "No hay ninguna reserva activa que cancelar.",
        }
    payload = CancelBookingInput.model_validate(args)
    if not payload.confirmed:
        return {
            "ok": False,
            "error": "cancelacion_no_confirmada",
            "message": "No cancelo la reserva sin tu confirmacion explicita.",
        }
    try:
        reservation = await cancel_reservation(
            ctx.session, reservation_id=ctx.reservation_id, restaurant_id=ctx.restaurant_id
        )
    except ReservationNotFoundError as exc:
        return {"ok": False, "error": "reserva_no_encontrada", "message": str(exc)}
    return {"ok": True, "reservation": _reservation_to_dict(reservation)}


create_booking_tool = Tool(
    name="create_booking",
    description=(
        "Crea una reserva para el cliente de la conversacion. Devuelve la reserva "
        "creada y, si aplica, needs_escalation con el motivo para derivar a un humano."
    ),
    input_schema=BookingInput.model_json_schema(),
    func=create_booking_tool_fn,
)

modify_booking_tool = Tool(
    name="modify_booking",
    description=(
        "Modifica la reserva activa de la conversacion (fecha, hora, comensales, "
        "zona preferida, notas)."
    ),
    input_schema=BookingModifyInput.model_json_schema(),
    func=modify_booking_tool_fn,
)

cancel_booking_tool = Tool(
    name="cancel_booking",
    description=(
        "Cancela la reserva activa de la conversacion. Requiere confirmed=true: "
        "nunca cancelar sin confirmacion explicita del cliente."
    ),
    input_schema=CancelBookingInput.model_json_schema(),
    func=cancel_booking_tool_fn,
)
