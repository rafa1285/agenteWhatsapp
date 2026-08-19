"""Motor de reservas: servicios puros, reutilizables por WhatsApp, voz y panel.

Convenciones:
- Los servicios hacen `flush` (nunca `commit`); el caller (router, tool del LLM,
  orquestador, test) decide el limite de la transaccion y commitea.
- Toda consulta filtra por `restaurant_id` (aislamiento multi-tenant).
- Las transiciones de ciclo de vida son idempotentes sobre su estado terminal;
  cualquier otra transicion ilegal lanza `ReservationConflictError`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as date_type
from datetime import time as time_type

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import EscalationReason
from app.core.models import Restaurant
from app.core.webhook import emit_reservation_event
from app.modules.availability.exceptions import NoAvailabilityError
from app.modules.availability.models import TableZone
from app.modules.availability.service import AssignmentResult, assign_table
from app.modules.customers.models import Customer
from app.modules.reminders.models import Reminder, ReminderStatus
from app.modules.reminders.service import schedule_24h_reminder
from app.modules.reservations.exceptions import (
    ReservationConflictError,
    ReservationNotFoundError,
    ReservationUnavailableError,
    RestaurantNotFoundError,
)
from app.modules.reservations.models import Reservation, ReservationStatus, SourceChannel

# Estados desde los que es legal cada transicion. Incluyen el estado terminal
# para que la operacion sea idempotente sobre el; el resto -> conflict.
_CONFIRMABLE = frozenset(
    {
        ReservationStatus.PENDING,
        ReservationStatus.PENDING_CONFIRMATION,
        ReservationStatus.CONFIRMED,
        ReservationStatus.MODIFIED,
    }
)
_CHECKINABLE = frozenset(
    {
        ReservationStatus.CONFIRMED,
        ReservationStatus.MODIFIED,
        ReservationStatus.COMPLETED,
    }
)
_NO_SHOWABLE = frozenset(
    {
        ReservationStatus.CONFIRMED,
        ReservationStatus.MODIFIED,
        ReservationStatus.NO_SHOW,
    }
)
_CANCELLABLE = frozenset(
    {
        ReservationStatus.PENDING,
        ReservationStatus.PENDING_CONFIRMATION,
        ReservationStatus.CONFIRMED,
        ReservationStatus.MODIFIED,
        ReservationStatus.CANCELLED,
    }
)
_MODIFIABLE = _CONFIRMABLE


@dataclass(frozen=True)
class CreateResult:
    """Resultado de crear una reserva, con la senal de escalacion al orquestador."""

    reservation: Reservation
    needs_escalation: bool = False
    escalation_reason: EscalationReason | None = None
    preferred_unavailable: bool = False


@dataclass(frozen=True)
class ModifyResult:
    """Resultado de modificar una reserva."""

    reservation: Reservation
    reassigned: bool = False
    preferred_unavailable: bool = False


def _assert_transition(
    status: ReservationStatus,
    allowed: frozenset[ReservationStatus],
    action: str,
) -> None:
    if status not in allowed:
        raise ReservationConflictError(
            f"No se puede {action} una reserva en estado '{status.value}'",
            data={"status": status.value},
        )


async def _get_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> Reservation:
    """Reserva por `id` + `restaurant_id` (invisible entre tenants)."""
    stmt = select(Reservation).where(
        Reservation.id == reservation_id,
        Reservation.restaurant_id == restaurant_id,
    )
    reservation = await session.scalar(stmt)
    if reservation is None:
        raise ReservationNotFoundError(f"Reserva no encontrada: {reservation_id}")
    return reservation


async def _cancel_pending_reminders(session: AsyncSession, *, reservation_id: uuid.UUID) -> None:
    """Cancela los recordatorios pendientes de la reserva."""
    await session.execute(
        update(Reminder)
        .where(
            Reminder.reservation_id == reservation_id,
            Reminder.status == ReminderStatus.PENDING,
        )
        .values(status=ReminderStatus.CANCELLED)
    )


async def create_reservation(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID,
    date: date_type,
    time: time_type,
    party_size: int,
    source_channel: SourceChannel,
    preferred_zone: TableZone | None = None,
    requested_table_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> CreateResult:
    """Crea una reserva y asigna mesa. Estado inicial segun riesgo, configurable.

    Orden de la decision de estado:
    - grupo grande (`party_size > large_group_threshold`) -> `pending_confirmation`
      con senal de escalacion al dueno (`needs_escalation` / `LARGE_GROUP`);
    - `auto_confirm_enabled = false` -> `pending_confirmation` (el restaurante
      decide cuando se autoconfirman las reservas);
    - riesgo de no-show (`requires_prior_confirmation` o
      `no_show_count >= no_show_threshold`) -> `pending_confirmation`;
    - resto -> `confirmed`.
    """
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise RestaurantNotFoundError(f"Restaurante no encontrado: {restaurant_id}")
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.restaurant_id != restaurant_id:
        raise ReservationConflictError("El cliente no pertenece a este restaurante")

    try:
        assignment: AssignmentResult = await assign_table(
            session,
            restaurant_id=restaurant_id,
            date=date,
            time=time,
            party_size=party_size,
            requested_table_id=requested_table_id,
            habitual_table_id=customer.preferred_table_id,
            preferred_zone=preferred_zone,
        )
    except NoAvailabilityError as exc:
        raise ReservationUnavailableError(exc.reason, alternatives=exc.alternatives) from exc

    if party_size > restaurant.large_group_threshold:
        status, needs_escalation, escalation_reason = (
            ReservationStatus.PENDING_CONFIRMATION,
            True,
            EscalationReason.LARGE_GROUP,
        )
    elif (
        not restaurant.auto_confirm_enabled
        or customer.requires_prior_confirmation
        or customer.no_show_count >= restaurant.no_show_threshold
    ):
        status, needs_escalation, escalation_reason = (
            ReservationStatus.PENDING_CONFIRMATION,
            False,
            None,
        )
    else:
        status, needs_escalation, escalation_reason = (
            ReservationStatus.CONFIRMED,
            False,
            None,
        )

    reservation = Reservation(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        table_id=assignment.table.id,
        date=date,
        time=time,
        party_size=party_size,
        preferred_zone=preferred_zone,
        status=status,
        source_channel=source_channel,
        notes=notes,
        assignment_reason=assignment.reason,
    )
    session.add(reservation)
    await session.flush()
    if status is ReservationStatus.CONFIRMED:
        # Una reserva que nace confirmada programa su recordatorio 24h.
        await schedule_24h_reminder(session, reservation=reservation, restaurant=restaurant)
    await emit_reservation_event("reservation.created", reservation)
    return CreateResult(
        reservation=reservation,
        needs_escalation=needs_escalation,
        escalation_reason=escalation_reason,
        preferred_unavailable=assignment.preferred_unavailable,
    )


async def confirm_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> Reservation:
    """Confirma una reserva. Idempotente si ya esta confirmada."""
    reservation = await _get_reservation(
        session, reservation_id=reservation_id, restaurant_id=restaurant_id
    )
    _assert_transition(reservation.status, _CONFIRMABLE, "confirmar")
    if reservation.status is not ReservationStatus.CONFIRMED:
        reservation.status = ReservationStatus.CONFIRMED
        await session.flush()
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is not None:
            await schedule_24h_reminder(session, reservation=reservation, restaurant=restaurant)
    return reservation


async def check_in_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> Reservation:
    """Registra la llegada: completa la reserva e incrementa `visit_count`.

    Idempotente si ya esta completada (no vuelve a incrementar).
    """
    reservation = await _get_reservation(
        session, reservation_id=reservation_id, restaurant_id=restaurant_id
    )
    _assert_transition(reservation.status, _CHECKINABLE, "registrar llegada")
    if reservation.status is ReservationStatus.COMPLETED:
        return reservation

    now = datetime.now(UTC)
    if reservation.customer_id is not None:
        customer = await session.get(Customer, reservation.customer_id)
        if customer is not None:
            customer.visit_count += 1
            customer.last_visit = now
    reservation.status = ReservationStatus.COMPLETED
    reservation.checked_in_at = now
    await session.flush()
    await emit_reservation_event("reservation.checked_in", reservation)
    return reservation


async def mark_no_show(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> Reservation:
    """Marca un no-show: incrementa `no_show_count` y, al superar el umbral,
    activa `requires_prior_confirmation` (§8.2). Idempotente si ya es no-show."""
    reservation = await _get_reservation(
        session, reservation_id=reservation_id, restaurant_id=restaurant_id
    )
    _assert_transition(reservation.status, _NO_SHOWABLE, "marcar como no-show")
    if reservation.status is ReservationStatus.NO_SHOW:
        return reservation

    if reservation.customer_id is not None:
        customer = await session.get(Customer, reservation.customer_id)
        restaurant = await session.get(Restaurant, restaurant_id)
        if customer is not None:
            customer.no_show_count += 1
            if restaurant is not None and customer.no_show_count >= restaurant.no_show_threshold:
                customer.requires_prior_confirmation = True
    reservation.status = ReservationStatus.NO_SHOW
    await session.flush()
    await emit_reservation_event("reservation.no_show", reservation)
    return reservation


async def modify_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    date: date_type | None = None,
    time: time_type | None = None,
    party_size: int | None = None,
    preferred_zone: TableZone | None = None,
    requested_table_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> ModifyResult:
    """Modifica una reserva.

    Si cambian fecha/hora/comensales/zona/mesa, re-asigna mesa
    (`reassigned=True`). Siempre que haya un cambio efectivo pasa a
    `modified` y cancela los recordatorios pendientes.
    """
    reservation = await _get_reservation(
        session, reservation_id=reservation_id, restaurant_id=restaurant_id
    )
    _assert_transition(reservation.status, _MODIFIABLE, "modificar")

    new_date = date if date is not None else reservation.date
    new_time = time if time is not None else reservation.time
    new_party = party_size if party_size is not None else reservation.party_size
    new_zone = preferred_zone if preferred_zone is not None else reservation.preferred_zone

    changed = (new_date, new_time, new_party) != (
        reservation.date,
        reservation.time,
        reservation.party_size,
    )
    if preferred_zone is not None and preferred_zone != reservation.preferred_zone:
        changed = True
    if requested_table_id is not None and requested_table_id != reservation.table_id:
        changed = True
    if notes is not None and notes != reservation.notes:
        changed = True
    if not changed:
        return ModifyResult(reservation=reservation, reassigned=False)

    reassigned = False
    preferred_unavailable = False
    reassign = (new_date, new_time, new_party, new_zone) != (
        reservation.date,
        reservation.time,
        reservation.party_size,
        reservation.preferred_zone,
    ) or requested_table_id is not None
    if reassign:
        customer = None
        if reservation.customer_id is not None:
            customer = await session.get(Customer, reservation.customer_id)
        try:
            assignment: AssignmentResult = await assign_table(
                session,
                restaurant_id=restaurant_id,
                date=new_date,
                time=new_time,
                party_size=new_party,
                requested_table_id=requested_table_id,
                habitual_table_id=customer.preferred_table_id if customer is not None else None,
                preferred_zone=new_zone,
            )
        except NoAvailabilityError as exc:
            raise ReservationUnavailableError(exc.reason, alternatives=exc.alternatives) from exc
        reservation.table_id = assignment.table.id
        reservation.assignment_reason = assignment.reason
        preferred_unavailable = assignment.preferred_unavailable
        reassigned = True

    reservation.date = new_date
    reservation.time = new_time
    reservation.party_size = new_party
    reservation.preferred_zone = new_zone
    if notes is not None:
        reservation.notes = notes
    reservation.status = ReservationStatus.MODIFIED
    await _cancel_pending_reminders(session, reservation_id=reservation.id)
    # La reserva modificada sigue necesitando su recordatorio: la cascada cancela
    # los PENDING y aquí se programa uno nuevo con la nueva fecha/hora.
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is not None:
        await schedule_24h_reminder(session, reservation=reservation, restaurant=restaurant)
    await session.flush()
    await emit_reservation_event("reservation.modified", reservation)
    return ModifyResult(
        reservation=reservation,
        reassigned=reassigned,
        preferred_unavailable=preferred_unavailable,
    )


async def cancel_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> Reservation:
    """Cancela una reserva y sus recordatorios pendientes. Idempotente."""
    reservation = await _get_reservation(
        session, reservation_id=reservation_id, restaurant_id=restaurant_id
    )
    _assert_transition(reservation.status, _CANCELLABLE, "cancelar")
    if reservation.status is ReservationStatus.CANCELLED:
        return reservation
    reservation.status = ReservationStatus.CANCELLED
    await _cancel_pending_reminders(session, reservation_id=reservation.id)
    await session.flush()
    await emit_reservation_event("reservation.cancelled", reservation)
    return reservation
