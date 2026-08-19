"""Tests de la tool `check_availability` (base de datos real)."""

from datetime import date as date_type

from app.agent.tool import ToolContext
from app.modules.availability.tools import check_availability_tool
from app.modules.reservations.models import SourceChannel

SERVICE_DATE = date_type(2026, 9, 15)


def _ctx(db_session, restaurant_id) -> ToolContext:
    return ToolContext(
        session=db_session,
        restaurant_id=restaurant_id,
        source_channel=SourceChannel.WHATSAPP,
    )


async def test_check_availability_tool_available(db_session, availability_setup):
    restaurant, tables = await availability_setup()
    result = await check_availability_tool.func(
        _ctx(db_session, restaurant.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    assert result["available"] is True
    assert result["reason"] == "available"
    assert {t["id"] for t in result["free_tables"]} == {str(t.id) for t in tables}


async def test_check_availability_tool_closed(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    result = await check_availability_tool.func(
        _ctx(db_session, restaurant.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    assert result["available"] is False
    assert result["reason"] == "closed"
    assert result["free_tables"] == []


async def test_check_availability_tool_multitenant(
    db_session, availability_setup, restaurant_factory
):
    _restaurant, _tables = await availability_setup()
    other = await restaurant_factory()
    result = await check_availability_tool.func(
        _ctx(db_session, other.id),
        {"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
    )
    # El restaurante B no ve el turno ni las mesas de A.
    assert result["available"] is False
    assert result["reason"] == "closed"
