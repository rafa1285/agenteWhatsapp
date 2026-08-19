"""Servicio de clientes: reconocimiento por teléfono (sección 12 del spec).

El teléfono es la clave única de reconocimiento (§12): cada interacción busca
al cliente por teléfono antes de responder, y si es la primera vez se crea una
fila mínima (solo teléfono) para que la conversación quede vinculada y se
acumule memoria en visitas siguientes. Lógica pura, sin dependencia HTTP.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer


def normalize_phone(phone: str) -> str:
    """Canoniza un teléfono E.164 a solo dígitos (sin `+`, espacios ni guiones).

    `+34 611 222 333` y `34611222333` deben identificar al mismo cliente; el
    formato canónico evita duplicados por formato. El panel debe usar el mismo.
    """
    return "".join(ch for ch in phone if ch.isdigit())


async def _find_customer(
    session: AsyncSession, *, restaurant_id: uuid.UUID, phone: str
) -> Customer | None:
    return await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == phone,
        )
    )


async def find_or_create_customer_by_phone(
    session: AsyncSession, *, restaurant_id: uuid.UUID, phone: str
) -> Customer:
    """Devuelve el cliente del restaurante con ese teléfono, o lo crea.

    Nunca cruza tenants: la búsqueda filtra por `restaurant_id`. Si entre el
    `select` y el `insert` otro request crea la misma fila (carrera), la
    violación del unique constraint se resuelve con rollback y relectura.
    """
    normalized = normalize_phone(phone)
    existing = await _find_customer(session, restaurant_id=restaurant_id, phone=normalized)
    if existing is not None:
        return existing

    customer = Customer(restaurant_id=restaurant_id, phone=normalized)
    session.add(customer)
    try:
        await session.flush()
    except IntegrityError:
        # Carrera: otro request creó el mismo (restaurant, phone) entre el
        # `select` y el `insert`. Un flush fallido deja la sesión en estado de
        # rollback obligatorio; se hace rollback y se relee. Quien llama a esta
        # función inserta su fila de dedup DESPUÉS, de modo que el rollback no
        # pierde la reserva de dedup de este mensaje.
        await session.rollback()
        existing = await _find_customer(session, restaurant_id=restaurant_id, phone=normalized)
        if existing is None:
            raise
        return existing
    return customer
