"""Motor de disponibilidad y asignacion de mesas.

Logica pura, sin dependencia HTTP: la reutilizan WhatsApp, voz y el panel.

Convenciones:
- Los servicios hacen `flush` (nunca `commit`); el caller decide el limite.
- Las ventanas de ocupacion son half-open `[start, start + duracion)` en
  minutos desde medianoche (naive, zona local del restaurante). Una reserva
  ocupa la mesa desde su hora hasta `hora + average_table_duration` del turno.
- Los turnos se resuelven para una fecha: si hay turnos con `special_date ==
  fecha`, esos sustituyen a los semanales (un dia especial reemplaza la
  programacion normal). El "activo" es el turno que contiene la hora pedida;
  si ninguno la contiene, `OUTSIDE_SERVICE_HOURS`.
- `preferred_zone` es una preferencia blanda: se intenta el mejor ajuste dentro
  de la zona y, si no hay, se cae a otra zona marcando `preferred_unavailable`.

Limitacion conocida (v1): un turno que cruza medianoche atiende las reservas de
su propio dia hasta las 24:00, pero no las de madrugada (00:00-`end_time`) del
dia siguiente, que exigirian mirar el turno del dia anterior.
"""

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from datetime import time as time_type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.availability.exceptions import NoAvailabilityError
from app.modules.availability.models import Shift, Table, TableZone
from app.modules.availability.schemas import (
    AvailabilityReason,
    AvailabilityResult,
    ShiftInfo,
    TableInfo,
)
from app.modules.reservations.models import (
    ACTIVE_RESERVATION_STATUSES,
    AssignmentReason,
    Reservation,
)


def _minutes(t: time_type) -> int:
    """Minutos desde medianoche (base para comparar ventanas)."""
    return t.hour * 60 + t.minute


@dataclass(frozen=True)
class AssignmentResult:
    """Asignacion de mesa (uso interno del modulo de reservas)."""

    table: Table
    reason: AssignmentReason
    preferred_unavailable: bool = False


@dataclass(frozen=True)
class _Evaluation:
    """Estado interno de una evaluacion de disponibilidad."""

    reason: AvailabilityReason
    shift: Shift | None
    free_tables: tuple[Table, ...]
    preferred_unavailable: bool = False


def _to_table_info(table: Table) -> TableInfo:
    return TableInfo(
        id=table.id,
        name=table.name,
        zone=table.zone,
        min_capacity=table.min_capacity,
        max_capacity=table.max_capacity,
    )


def _to_shift_info(shift: Shift, date: date_type) -> ShiftInfo:
    return ShiftInfo(
        date=date,
        start_time=shift.start_time,
        end_time=shift.end_time,
        duration_minutes=shift.average_table_duration,
        max_capacity=shift.max_capacity,
    )


async def _resolve_shifts(
    session: AsyncSession, *, restaurant_id: uuid.UUID, date: date_type
) -> list[Shift]:
    """Turnos que aplican a la fecha (tenant-scoped).

    Si existen turnos con `special_date == fecha`, sustituyen a los semanales:
    un dia especial reemplaza la programacion normal de ese dia.
    """
    if special := list(
        await session.scalars(
            select(Shift)
            .where(Shift.restaurant_id == restaurant_id, Shift.special_date == date)
            .order_by(Shift.start_time)
        )
    ):
        return special
    weekday = date.isoweekday() - 1  # 0=lunes ... 6=domingo (igual que Shift.weekday)
    return list(
        await session.scalars(
            select(Shift)
            .where(Shift.restaurant_id == restaurant_id, Shift.weekday == weekday)
            .order_by(Shift.start_time)
        )
    )


def _containing_shift(shifts: list[Shift], t_min: int) -> Shift | None:
    """Primer turno cuya ventana contiene `t_min` (cruza medianoche si end <= start)."""
    for shift in shifts:
        start = _minutes(shift.start_time)
        end = _minutes(shift.end_time)
        if end <= start:
            end += 1440  # el turno acaba pasada la medianoche
        if start <= t_min < end:
            return shift
    return None


async def _load_busy_table_ids(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    date: date_type,
    start_min: int,
    end_min: int,
    duration_min: int,
) -> set[uuid.UUID]:
    """IDs de mesas ocupadas en `[start_min, end_min)` por reservas activas."""
    stmt = (
        select(Reservation.table_id, Reservation.time)
        .where(
            Reservation.restaurant_id == restaurant_id,
            Reservation.date == date,
            Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            Reservation.table_id.is_not(None),
        )
        .order_by(Reservation.time)
    )
    rows = await session.execute(stmt)
    busy: set[uuid.UUID] = set()
    for table_id, res_time in rows:
        if table_id is None or res_time is None:
            continue
        r_start = _minutes(res_time)
        r_end = r_start + duration_min
        if start_min < r_end and r_start < end_min:  # solapamiento half-open
            busy.add(table_id)
    return busy


async def _load_fitting_tables(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    party_size: int,
) -> list[Table]:
    """Mesas del restaurante cuya capacidad admite `party_size` (sin partir mesas)."""
    stmt = (
        select(Table)
        .where(
            Table.restaurant_id == restaurant_id,
            Table.min_capacity <= party_size,
            Table.max_capacity >= party_size,
        )
        .order_by(Table.name, Table.id)
    )
    return list(await session.scalars(stmt))


async def _evaluate(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    date: date_type,
    time: time_type,
    party_size: int,
    preferred_zone: TableZone | None = None,
) -> _Evaluation:
    """Evalua la peticion: turno -> aforo -> mesas libres (que quepan solas)."""
    t_min = _minutes(time)
    shifts = await _resolve_shifts(session, restaurant_id=restaurant_id, date=date)
    if not shifts:
        return _Evaluation(AvailabilityReason.CLOSED, None, ())
    active = _containing_shift(shifts, t_min)
    if active is None:
        return _Evaluation(AvailabilityReason.OUTSIDE_SERVICE_HOURS, None, ())
    if party_size > active.max_capacity:
        return _Evaluation(AvailabilityReason.AFORO_EXCEEDED, active, ())

    end_min = t_min + active.average_table_duration
    busy = await _load_busy_table_ids(
        session,
        restaurant_id=restaurant_id,
        date=date,
        start_min=t_min,
        end_min=end_min,
        duration_min=active.average_table_duration,
    )
    fitting = await _load_fitting_tables(
        session, restaurant_id=restaurant_id, party_size=party_size
    )
    free = tuple(t for t in fitting if t.id not in busy)

    if preferred_zone is not None:
        in_zone = tuple(t for t in free if t.zone == preferred_zone)
        if in_zone:
            return _Evaluation(AvailabilityReason.AVAILABLE, active, in_zone)
        if free:
            # Preferencia blanda: hay hueco, pero no en la zona pedida.
            return _Evaluation(
                AvailabilityReason.AVAILABLE, active, free, preferred_unavailable=True
            )
        return _Evaluation(AvailabilityReason.NO_TABLE_FOR_PARTY, active, ())

    if free:
        return _Evaluation(AvailabilityReason.AVAILABLE, active, free)
    return _Evaluation(AvailabilityReason.NO_TABLE_FOR_PARTY, active, ())


async def check_availability(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    date: date_type,
    time: time_type,
    party_size: int,
    preferred_zone: TableZone | None = None,
) -> AvailabilityResult:
    """Comprueba si una peticion se puede atender. Nunca lanza."""
    evaluation = await _evaluate(
        session,
        restaurant_id=restaurant_id,
        date=date,
        time=time,
        party_size=party_size,
        preferred_zone=preferred_zone,
    )
    return AvailabilityResult(
        available=evaluation.reason is AvailabilityReason.AVAILABLE,
        reason=evaluation.reason,
        preferred_unavailable=evaluation.preferred_unavailable,
        shift=_to_shift_info(evaluation.shift, date) if evaluation.shift is not None else None,
        free_tables=[_to_table_info(t) for t in evaluation.free_tables],
    )


async def assign_table(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    date: date_type,
    time: time_type,
    party_size: int,
    requested_table_id: uuid.UUID | None = None,
    habitual_table_id: uuid.UUID | None = None,
    preferred_zone: TableZone | None = None,
) -> AssignmentResult:
    """Asigna mesa segun §8.1: solicitada -> habitual -> mejor ajuste por capacidad.

    Lanza `NoAvailabilityError` si no hay mesa libre que quepa.
    """
    evaluation = await _evaluate(
        session,
        restaurant_id=restaurant_id,
        date=date,
        time=time,
        party_size=party_size,
        preferred_zone=preferred_zone,
    )
    if evaluation.reason is not AvailabilityReason.AVAILABLE:
        raise NoAvailabilityError(evaluation.reason)

    free = evaluation.free_tables
    if not free:
        raise NoAvailabilityError(AvailabilityReason.NO_TABLE_FOR_PARTY)

    # 1) Mesa pedida explicitamente, si sigue libre.
    if requested_table_id is not None:
        for table in free:
            if table.id == requested_table_id:
                return AssignmentResult(table, AssignmentReason.SPECIFIC_REQUEST)
    # 2) Mesa habitual del cliente, si sigue libre.
    if habitual_table_id is not None:
        for table in free:
            if table.id == habitual_table_id:
                return AssignmentResult(table, AssignmentReason.HABITUAL_TABLE)
    # 3) Mejor ajuste: la de menor max_capacity que quepa (tie-break determinista).
    best = min(free, key=lambda t: (t.max_capacity, t.name, t.id))
    return AssignmentResult(
        best,
        AssignmentReason.STANDARD_AVAILABILITY,
        evaluation.preferred_unavailable,
    )
