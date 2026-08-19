"""Tests del motor de disponibilidad (servicios puros, con base de datos)."""

from datetime import date, time

import pytest
from app.modules.availability.exceptions import NoAvailabilityError
from app.modules.availability.models import Shift, TableZone
from app.modules.availability.schemas import AvailabilityReason
from app.modules.availability.service import assign_table, check_availability
from app.modules.reservations.models import AssignmentReason, ReservationStatus

SERVICE_DATE = date(2026, 9, 15)  # martes


async def test_available_when_table_free(db_session, availability_setup):
    restaurant, tables = await availability_setup()
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
    )
    assert result.available is True
    assert result.reason is AvailabilityReason.AVAILABLE
    assert result.shift is not None
    assert result.shift.duration_minutes == 90
    assert {t.id for t in result.free_tables} == {t.id for t in tables}


async def test_overlap_blocks_and_frees_after_window(
    db_session, availability_setup, reservation_factory, customer_factory
):
    restaurant, [table] = await availability_setup(tables=((1, 4),))
    customer = await customer_factory(restaurant.id)
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        status=ReservationStatus.CONFIRMED,
    )
    blocked = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
    )
    assert blocked.available is False
    assert blocked.reason is AvailabilityReason.NO_TABLE_FOR_PARTY

    # Ventana de ocupacion [14:00, 15:30): a las 15:30 la mesa queda libre.
    freed = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(15, 30),
        party_size=2,
    )
    assert freed.available is True
    assert {t.id for t in freed.free_tables} == {table.id}


async def test_cancelled_and_completed_do_not_block(
    db_session, availability_setup, reservation_factory, customer_factory
):
    restaurant, [table] = await availability_setup(tables=((1, 4),))
    customer = await customer_factory(restaurant.id)
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        status=ReservationStatus.CANCELLED,
    )
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time(15, 0),
        status=ReservationStatus.COMPLETED,
    )
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
    )
    assert result.available is True


async def test_closed_without_shift(db_session, restaurant_factory, table_factory):
    restaurant = await restaurant_factory()
    await table_factory(restaurant.id)
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
    )
    assert result.available is False
    assert result.reason is AvailabilityReason.CLOSED
    assert result.shift is None
    assert result.free_tables == []


async def test_special_date_replaces_weekday(db_session, availability_setup, shift_factory):
    """Si existe un turno special_date, sustituye al semanal de ese dia."""
    restaurant, _ = await availability_setup(max_capacity=20)
    db_session.add(
        Shift(
            restaurant_id=restaurant.id,
            special_date=SERVICE_DATE,
            start_time=time(13, 0),
            end_time=time(16, 0),
            average_table_duration=90,
            max_capacity=4,
        )
    )
    await db_session.flush()
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=6,
    )
    # El turno especial (aforo 4) gana al semanal (aforo 20): 6 > 4 -> aforo.
    assert result.available is False
    assert result.reason is AvailabilityReason.AFORO_EXCEEDED


async def test_outside_service_hours(db_session, availability_setup):
    restaurant, _ = await availability_setup()
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(17, 0),
        party_size=2,
    )
    assert result.available is False
    assert result.reason is AvailabilityReason.OUTSIDE_SERVICE_HOURS


async def test_aforo_exceeded(db_session, availability_setup):
    restaurant, _ = await availability_setup(max_capacity=20)
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=25,
    )
    assert result.available is False
    assert result.reason is AvailabilityReason.AFORO_EXCEEDED


async def test_no_table_for_party(db_session, availability_setup):
    restaurant, _ = await availability_setup(tables=((1, 2),))
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=4,
    )
    assert result.available is False
    assert result.reason is AvailabilityReason.NO_TABLE_FOR_PARTY


async def test_preferred_unavailable_falls_back_to_other_zone(
    db_session, availability_setup, table_factory, reservation_factory, customer_factory
):
    restaurant, _ = await availability_setup(tables=())
    indoor = await table_factory(
        restaurant.id, name="Interior", zone=TableZone.INDOOR, min_capacity=1, max_capacity=4
    )
    terrace = await table_factory(
        restaurant.id, name="Terraza", zone=TableZone.TERRACE, min_capacity=1, max_capacity=4
    )
    customer = await customer_factory(restaurant.id)
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=terrace.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        status=ReservationStatus.CONFIRMED,
    )
    result = await check_availability(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        preferred_zone=TableZone.TERRACE,
    )
    # Terraza ocupada: se informa que la zona preferida no esta disponible y
    # se ofrecen las mesas libres de otras zonas.
    assert result.available is True
    assert result.preferred_unavailable is True
    assert [t.id for t in result.free_tables] == [indoor.id]


async def test_assign_specific_request(db_session, availability_setup):
    restaurant, tables = await availability_setup()
    result = await assign_table(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        requested_table_id=tables[1].id,
    )
    assert result.table.id == tables[1].id
    assert result.reason is AssignmentReason.SPECIFIC_REQUEST


async def test_assign_habitual_table(db_session, availability_setup, table_factory):
    restaurant, tables = await availability_setup(tables=((1, 2), (1, 8)))
    result = await assign_table(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        habitual_table_id=tables[1].id,
    )
    # La mesa habitual es la grande (8); el mejor ajuste habria sido la pequena (2).
    assert result.table.id == tables[1].id
    assert result.reason is AssignmentReason.HABITUAL_TABLE


async def test_assign_best_fit_by_capacity(db_session, availability_setup, table_factory):
    restaurant, tables = await availability_setup(tables=((1, 2), (1, 6), (1, 8)))
    result = await assign_table(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=3,
    )
    # Para 3 comensales caben la de 6 y la de 8; se elige la menor (6).
    assert result.table.id == tables[1].id
    assert result.reason is AssignmentReason.STANDARD_AVAILABILITY


async def test_assign_falls_back_when_requested_occupied(
    db_session, availability_setup, reservation_factory, customer_factory
):
    restaurant, tables = await availability_setup()
    customer = await customer_factory(restaurant.id)
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time(14, 0),
        status=ReservationStatus.CONFIRMED,
    )
    result = await assign_table(
        db_session,
        restaurant_id=restaurant.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        requested_table_id=tables[0].id,
    )
    # La mesa pedida esta ocupada -> se cae al mejor ajuste (la otra).
    assert result.table.id == tables[1].id
    assert result.reason is AssignmentReason.STANDARD_AVAILABILITY


async def test_assign_raises_when_no_table(
    db_session, availability_setup, reservation_factory, customer_factory
):
    restaurant, [table] = await availability_setup(tables=((1, 4),))
    customer = await customer_factory(restaurant.id)
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        status=ReservationStatus.CONFIRMED,
    )
    with pytest.raises(NoAvailabilityError) as exc_info:
        await assign_table(
            db_session,
            restaurant_id=restaurant.id,
            date=SERVICE_DATE,
            time=time(14, 0),
            party_size=2,
        )
    assert exc_info.value.reason is AvailabilityReason.NO_TABLE_FOR_PARTY
    assert exc_info.value.alternatives == []
