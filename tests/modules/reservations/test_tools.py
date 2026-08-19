"""Tests de las tools de reservas (base de datos real)."""

from datetime import date as date_type
from datetime import time as time_type

from app.agent.models import Escalation
from app.agent.tool import ToolContext
from app.modules.reservations.models import ReservationStatus, SourceChannel
from app.modules.reservations.tools import (
    cancel_booking_tool,
    create_booking_tool,
    modify_booking_tool,
)
from sqlalchemy import func, select

SERVICE_DATE = date_type(2026, 9, 15)


def _ctx(
    db_session,
    restaurant_id,
    *,
    customer_id=None,
    reservation_id=None,
) -> ToolContext:
    return ToolContext(
        session=db_session,
        restaurant_id=restaurant_id,
        source_channel=SourceChannel.WHATSAPP,
        customer_id=customer_id,
        reservation_id=reservation_id,
    )


async def test_create_booking_confirmed(db_session, reservation_context):
    restaurant, customer, tables = await reservation_context()
    result = await create_booking_tool.func(
        _ctx(db_session, restaurant.id, customer_id=customer.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    assert result["ok"] is True
    assert result["reservation"]["status"] == "confirmed"
    assert result["reservation"]["table_id"] == str(tables[0].id)
    assert result["needs_escalation"] is False


async def test_create_booking_large_group_surfaces_escalation(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context(
        restaurant_overrides={"large_group_threshold": 8}, tables=((1, 12),)
    )
    result = await create_booking_tool.func(
        _ctx(db_session, restaurant.id, customer_id=customer.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 10},
    )
    assert result["ok"] is True
    assert result["reservation"]["status"] == "pending_confirmation"
    assert result["needs_escalation"] is True
    assert result["escalation_reason"] == "large_group"
    # La senal es para el orquestador: la tool no crea la fila de Escalation.
    count = await db_session.scalar(select(func.count()).select_from(Escalation))
    assert count == 0


async def test_create_booking_without_customer(db_session, reservation_context):
    restaurant, _customer, _tables = await reservation_context()
    result = await create_booking_tool.func(
        _ctx(db_session, restaurant.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    assert result["ok"] is False
    assert result["error"] == "customer_desconocido"


async def test_create_booking_unavailable_surfaces_alternatives(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, [table] = await reservation_context(tables=((1, 4),))
    await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=table.id, date=SERVICE_DATE
    )
    result = await create_booking_tool.func(
        _ctx(db_session, restaurant.id, customer_id=customer.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    assert result["ok"] is False
    assert result["error"] == "sin_disponibilidad"
    assert result["reason"] == "no_table_for_party"
    assert result["alternatives"] == []


async def test_create_booking_customer_of_other_tenant(
    db_session, reservation_context, restaurant_factory, customer_factory
):
    restaurant, _customer, _tables = await reservation_context()
    other = await restaurant_factory()
    other_customer = await customer_factory(other.id)
    result = await create_booking_tool.func(
        _ctx(db_session, restaurant.id, customer_id=other_customer.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    assert result["ok"] is False
    assert result["error"] == "conflicto"


async def test_modify_booking_reassigns(db_session, reservation_context, reservation_factory):
    restaurant, customer, tables = await reservation_context(tables=((1, 2), (1, 4)))
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time_type(14, 0),
    )
    # Ocupar la mesa pequena a las 15:00 para forzar el cambio de mesa al modificar.
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time_type(15, 0),
    )
    result = await modify_booking_tool.func(
        _ctx(db_session, restaurant.id, reservation_id=reservation.id),
        {"time": "15:00"},
    )
    assert result["ok"] is True
    assert result["reassigned"] is True
    assert result["reservation"]["table_id"] == str(tables[1].id)
    assert result["reservation"]["status"] == "modified"


async def test_modify_booking_unavailable(db_session, reservation_context, reservation_factory):
    restaurant, customer, [table] = await reservation_context(tables=((1, 4),))
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time_type(14, 0),
    )
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time_type(15, 0),
    )
    result = await modify_booking_tool.func(
        _ctx(db_session, restaurant.id, reservation_id=reservation.id),
        {"time": "15:00"},
    )
    assert result["ok"] is False
    assert result["error"] == "sin_disponibilidad"


async def test_cancel_booking_requires_confirmed(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    result = await cancel_booking_tool.func(
        _ctx(db_session, restaurant.id, reservation_id=reservation.id),
        {"confirmed": False},
    )
    assert result["ok"] is False
    assert result["error"] == "cancelacion_no_confirmada"
    # La reserva sigue activa: no se toca sin confirmacion explicita.
    assert reservation.status is ReservationStatus.CONFIRMED


async def test_cancel_booking_cancels(db_session, reservation_context, reservation_factory):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    result = await cancel_booking_tool.func(
        _ctx(db_session, restaurant.id, reservation_id=reservation.id),
        {"confirmed": True},
    )
    assert result["ok"] is True
    assert result["reservation"]["status"] == "cancelled"


async def test_cancel_booking_reservation_of_other_tenant(
    db_session, reservation_context, restaurant_factory, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    other = await restaurant_factory()
    result = await cancel_booking_tool.func(
        _ctx(db_session, other.id, reservation_id=reservation.id),
        {"confirmed": True},
    )
    assert result["ok"] is False
    assert result["error"] == "reserva_no_encontrada"
