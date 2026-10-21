"""Fixtures de base de datos y factories para los tests de servicio.

Se usa una base PostgreSQL propia (`agente_whatsapp_test`), creada a demanda en
el mismo servidor de desarrollo, con un motor de tests que usa `NullPool`:
cada conexion se abre y se cierra dentro de un unico event loop, de modo que
ninguna conexion reaparecida cruce entre los loops que crea pytest-asyncio
(si cruzara, fallaria con "Event loop is closed").

Los tests de metadata existentes no piden `db_session`: siguen sin tocar base
de datos.
"""

import asyncio
import itertools
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from datetime import time as time_type
from os import environ

import app.db.models  # noqa: F401  # registra todos los modelos en Base.metadata
import asyncpg
import pytest
import pytest_asyncio
from app.core.models import Restaurant
from app.core.settings import get_settings, settings
from app.db.base import Base
from app.modules.availability.models import Shift, Table, TableZone
from app.modules.customers.models import Customer
from app.modules.reminders.models import Reminder, ReminderChannel, ReminderStatus, ReminderType
from app.modules.reservations.models import Reservation, ReservationStatus, SourceChannel
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


@pytest.fixture(scope="session", autouse=True)
def enable_testing_mode():
    """Habilita TESTING=True para toda la session de tests (deshabilita webhooks).

    `USE_MEDIA_STREAMS` se fija en False aunque el `.env` local lo tenga en True:
    el modo de voz (turnos `<Say>`/`<Gather>` o stream en tiempo real) cambia el
    TwiML del saludo, y los tests no pueden depender de una bandera de desarrollo.
    Los tests que quieren el otro modo la levantan con `monkeypatch.setattr`.
    """
    settings.TESTING = True
    settings.USE_MEDIA_STREAMS = False
    get_settings.cache_clear()
    yield
    settings.TESTING = False

TEST_DATABASE_URL = environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://Rafa@localhost:5432/agente_whatsapp_test",
)
ADMIN_DSN = environ.get("ADMIN_DSN", "postgresql://Rafa@localhost:5432/postgres")


def _test_database_name() -> str:
    return make_url(TEST_DATABASE_URL).database


async def _ensure_test_database() -> None:
    """Crea la base de tests si no existe (autocommit, DDL no transaccional).

    Note: The test DB may have foreign tables from Laravel migrations (owner_users,
    restaurant_daily_stats) that reference our tables. We drop and recreate to start
    completely clean since DROP DATABASE can't run in a transaction.
    """
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _test_database_name()
        )
        if exists:
            # Drop existing database to clear any foreign tables from Laravel migrations
            await conn.execute(f'DROP DATABASE "{_test_database_name()}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{_test_database_name()}"')
    finally:
        await conn.close()


async def _init_schema(engine: AsyncEngine) -> None:
    """Esquema al dia desde los modelos (drop_all + create_all)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _truncate_all(engine: AsyncEngine) -> None:
    """Vacia todas las tablas (RESTART IDENTITY CASCADE) antes de cada test."""
    async with engine.begin() as conn:
        tables = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def test_engine() -> AsyncEngine:
    """Motor de tests (NullPool) con la base creada y el esquema al dia."""
    asyncio.run(_ensure_test_database())

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, pool_pre_ping=True)
    asyncio.run(_init_schema(engine))
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncSession:
    """Sesion limpia por test: vacia las tablas al empezar y nunca commitea."""
    await _truncate_all(test_engine)
    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


_phone_counter = itertools.count(1)


@pytest_asyncio.fixture
async def restaurant_factory(db_session: AsyncSession):
    async def _factory(**overrides):
        defaults = {
            "name": "Restaurante Test",
            "public_phone": "+34910000000",
            "whatsapp_number_id": "wa-100000",
            "voice_number": "+34910000001",
            "timezone": "Europe/Madrid",
            "no_show_threshold": 2,
            "large_group_threshold": 8,
            "auto_confirm_enabled": True,
        }
        restaurant = Restaurant(**{**defaults, **overrides})
        db_session.add(restaurant)
        await db_session.flush()
        return restaurant

    return _factory


@pytest_asyncio.fixture
async def table_factory(db_session: AsyncSession):
    async def _factory(
        restaurant_id,
        *,
        name="Mesa Test",
        zone=TableZone.INDOOR,
        min_capacity=1,
        max_capacity=4,
    ):
        table = Table(
            restaurant_id=restaurant_id,
            name=name,
            zone=zone,
            min_capacity=min_capacity,
            max_capacity=max_capacity,
        )
        db_session.add(table)
        await db_session.flush()
        return table

    return _factory


@pytest_asyncio.fixture
async def shift_factory(db_session: AsyncSession):
    async def _factory(
        restaurant_id,
        *,
        date: date_type,
        start_time: time_type = time_type(13, 0),
        end_time: time_type = time_type(16, 0),
        average_table_duration: int = 90,
        max_capacity: int = 20,
    ):
        shift = Shift(
            restaurant_id=restaurant_id,
            weekday=date.isoweekday() - 1,
            start_time=start_time,
            end_time=end_time,
            average_table_duration=average_table_duration,
            max_capacity=max_capacity,
        )
        db_session.add(shift)
        await db_session.flush()
        return shift

    return _factory


@pytest_asyncio.fixture
async def customer_factory(db_session: AsyncSession):
    async def _factory(
        restaurant_id,
        *,
        phone=None,
        name="Cliente Test",
        preferred_table_id=None,
        no_show_count=0,
        requires_prior_confirmation=False,
    ):
        customer = Customer(
            restaurant_id=restaurant_id,
            phone=phone or f"+346{next(_phone_counter):08d}",
            name=name,
            preferred_table_id=preferred_table_id,
            no_show_count=no_show_count,
            requires_prior_confirmation=requires_prior_confirmation,
            visit_count=0,
        )
        db_session.add(customer)
        await db_session.flush()
        return customer

    return _factory


@pytest_asyncio.fixture
async def reservation_factory(db_session: AsyncSession):
    async def _factory(
        restaurant_id,
        *,
        customer_id,
        table_id,
        date: date_type,
        time: time_type = time_type(14, 0),
        party_size=2,
        preferred_zone=None,
        status=ReservationStatus.CONFIRMED,
        source_channel=SourceChannel.WHATSAPP,
        notes=None,
    ):
        reservation = Reservation(
            restaurant_id=restaurant_id,
            customer_id=customer_id,
            table_id=table_id,
            date=date,
            time=time,
            party_size=party_size,
            preferred_zone=preferred_zone,
            status=status,
            source_channel=source_channel,
            notes=notes,
        )
        db_session.add(reservation)
        await db_session.flush()
        return reservation

    return _factory


@pytest_asyncio.fixture
async def reminder_factory(db_session: AsyncSession):
    async def _factory(
        reservation_id,
        *,
        type=ReminderType.REMINDER_24H,
        status=ReminderStatus.PENDING,
        scheduled_send_at=None,
        channel=ReminderChannel.WHATSAPP,
        attempts=0,
    ):
        # Por defecto, un recordatorio "vencido" (pasado reciente): el tick lo recoge.
        reminder = Reminder(
            reservation_id=reservation_id,
            type=type,
            status=status,
            scheduled_send_at=scheduled_send_at or datetime.now(UTC) - timedelta(minutes=5),
            channel=channel,
            attempts=attempts,
        )
        db_session.add(reminder)
        await db_session.flush()
        return reminder

    return _factory


#: Fecha fija de los tests de escenario (martes 2026-09-15).
SERVICE_DATE = date_type(2026, 9, 15)


@pytest_asyncio.fixture
async def availability_setup(restaurant_factory, shift_factory, table_factory):
    """Restaurante con turno (13:00-16:00, 90 min) y mesas, sin reservas."""

    async def _make(*, date=SERVICE_DATE, max_capacity=20, tables=((1, 4), (1, 6))):
        restaurant = await restaurant_factory()
        await shift_factory(restaurant.id, date=date, max_capacity=max_capacity)
        created = [
            await table_factory(restaurant.id, name=f"M{idx}", min_capacity=mn, max_capacity=mx)
            for idx, (mn, mx) in enumerate(tables, start=1)
        ]
        return restaurant, created

    return _make


@pytest_asyncio.fixture
async def reservation_context(restaurant_factory, shift_factory, table_factory, customer_factory):
    """Restaurante con turno, mesas y un cliente, sin reservas."""

    async def _make(
        *,
        date=SERVICE_DATE,
        restaurant_overrides=None,
        customer_overrides=None,
        tables=((1, 4), (1, 6)),
    ):
        restaurant = await restaurant_factory(**(restaurant_overrides or {}))
        await shift_factory(restaurant.id, date=date)
        created = [
            await table_factory(restaurant.id, name=f"M{idx}", min_capacity=mn, max_capacity=mx)
            for idx, (mn, mx) in enumerate(tables, start=1)
        ]
        customer = await customer_factory(restaurant.id, **(customer_overrides or {}))
        return restaurant, customer, created

    return _make


@pytest_asyncio.fixture
async def asgi_client(test_engine: AsyncEngine):
    """Cliente ASGI e2e: app real con DB, LLM y gateway de tests overrideados.

    Vacía la BD al arrancar (como `db_session`) y sustituye las dependencias
    por `FakeLLMClient` y `FakeWhatsAppGateway` para no tocar red. El endpoint
    commitea contra `agente_whatsapp_test`; los tests deben `commit` los datos
    que creen con `db_session` para que la app (sesión distinta, NullPool) los
    vea.
    """
    from app.agent.client import FakeLLMClient
    from app.channels.whatsapp.dependencies import get_llm_client, get_whatsapp_gateway
    from app.channels.whatsapp.gateway import FakeWhatsAppGateway
    from app.db.session import get_db_session
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    await _truncate_all(test_engine)

    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _db_session():
        async with session_factory() as session:
            yield session

    app = create_app()
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()
    app.dependency_overrides[get_db_session] = _db_session
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_whatsapp_gateway] = lambda: gateway

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, llm, gateway
    finally:
        app.dependency_overrides.clear()
