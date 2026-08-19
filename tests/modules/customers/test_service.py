"""Tests del servicio de clientes (reconocimiento por teléfono, §12)."""

from app.core.models import Restaurant
from app.modules.customers.models import Customer
from app.modules.customers.service import (
    find_or_create_customer_by_phone,
    normalize_phone,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_normalize_phone() -> None:
    assert normalize_phone("+34 611 222 333") == "34611222333"
    assert normalize_phone("34611222333") == "34611222333"
    assert normalize_phone("+34-611-222-333") == "34611222333"
    assert normalize_phone("611222333") == "611222333"


async def test_creates_new_customer(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    customer = await find_or_create_customer_by_phone(
        db_session, restaurant_id=restaurant.id, phone="+34611111111"
    )
    assert customer.id is not None
    assert customer.phone == "34611111111"
    assert customer.restaurant_id == restaurant.id


async def test_reuses_existing_customer(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    first = await find_or_create_customer_by_phone(
        db_session, restaurant_id=restaurant.id, phone="+34611111111"
    )
    second = await find_or_create_customer_by_phone(
        db_session, restaurant_id=restaurant.id, phone="34611111111"
    )
    assert second.id == first.id
    count = await db_session.scalar(select(func.count()).select_from(Customer))
    assert count == 1


async def test_same_phone_different_restaurant_are_separate(db_session, restaurant_factory):
    restaurant_a = await restaurant_factory(name="Rest A")
    restaurant_b = await restaurant_factory(name="Rest B")
    customer_a = await find_or_create_customer_by_phone(
        db_session, restaurant_id=restaurant_a.id, phone="+34611111111"
    )
    customer_b = await find_or_create_customer_by_phone(
        db_session, restaurant_id=restaurant_b.id, phone="+34611111111"
    )
    assert customer_a.id != customer_b.id
    assert customer_a.restaurant_id == restaurant_a.id
    assert customer_b.restaurant_id == restaurant_b.id


async def test_race_resolved_by_rollback_and_reread(db_session, test_engine, monkeypatch) -> None:
    """Carrera: el select no ve la fila pero el insert la viola (unique).

    La fila existente se commitea en otra sesión para que sobreviva al rollback
    que hace `find_or_create_customer_by_phone` al chocar con el unique.
    """
    import app.modules.customers.service as svc

    committed = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with committed() as other:
        restaurant = Restaurant(
            name="Rest Race",
            public_phone="+34910000000",
            whatsapp_number_id="wa-race",
            voice_number="+34910000001",
            active=True,
        )
        other.add(restaurant)
        await other.flush()  # el id (gen_random_uuid) se puebla en el flush
        existing = Customer(restaurant_id=restaurant.id, phone="34611111111")
        other.add(existing)
        await other.commit()
        existing_id = existing.id

    original_find = svc._find_customer
    calls = 0

    async def stale_find(session, *, restaurant_id, phone):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None  # vista obsoleta: el select no ve la fila
        return await original_find(session, restaurant_id=restaurant_id, phone=phone)

    monkeypatch.setattr(svc, "_find_customer", stale_find)
    result = await find_or_create_customer_by_phone(
        db_session, restaurant_id=restaurant.id, phone="34611111111"
    )
    assert result.id == existing_id
    count = await db_session.scalar(select(func.count()).select_from(Customer))
    assert count == 1
