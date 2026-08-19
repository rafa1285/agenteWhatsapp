"""Router REST de clientes (CRUD multi-tenant, auth JWT)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.models import Restaurant
from app.modules.customers.models import Customer
from app.modules.customers.schemas import CustomerInfo

router = APIRouter(prefix="/api/v1/customers", tags=["customers"], dependencies=[Depends(get_current_restaurant)])


@router.get("", response_model=list[CustomerInfo])
async def list_customers(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    search: Annotated[str | None, Query(min_length=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CustomerInfo]:
    """Listar clientes del restaurante (búsqueda opcional por nombre/teléfono)."""
    stmt = select(Customer).where(Customer.restaurant_id == restaurant.id)
    if search:
        stmt = stmt.where(
            (Customer.name.ilike(f"%{search}%")) | (Customer.phone.ilike(f"%{search}%"))
        )
    stmt = stmt.order_by(Customer.visit_count.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=CustomerInfo, status_code=status.HTTP_201_CREATED)
async def create_customer(
    phone: Annotated[str, Query(min_length=3, max_length=32)],
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[str | None, Query(max_length=120)] = None,
    allergies: Annotated[str | None, Query()] = None,
    preferences: Annotated[str | None, Query()] = None,
    preferred_language: Annotated[str | None, Query(max_length=8)] = "es",
) -> CustomerInfo:
    """Crear cliente nuevo."""
    from app.modules.customers.service import find_or_create_customer_by_phone

    # Usamos el service para dedup por teléfono
    customer = await find_or_create_customer_by_phone(
        session=session,
        restaurant_id=restaurant.id,
        phone=phone,
    )

    if name is not None:
        customer.name = name
    if allergies is not None:
        customer.allergies = allergies
    if preferences is not None:
        customer.preferences = preferences
    if preferred_language is not None:
        customer.preferred_language = preferred_language

    await session.flush()
    await session.commit()
    return customer


@router.get("/{customer_id}", response_model=CustomerInfo)
async def get_customer(
    customer_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomerInfo:
    """Obtener cliente por ID (verifica tenant)."""
    from uuid import UUID

    try:
        c_id = UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    customer = await session.get(Customer, c_id)
    if not customer or customer.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


@router.patch("/{customer_id}")
async def update_customer(
    customer_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[str | None, Query(max_length=120)] = None,
    allergies: Annotated[str | None, Query()] = None,
    preferences: Annotated[str | None, Query()] = None,
    preferred_language: Annotated[str | None, Query(max_length=8)] = None,
) -> CustomerInfo:
    """Actualizar cliente (campos opcionales)."""
    from uuid import UUID

    try:
        c_id = UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    customer = await session.get(Customer, c_id)
    if not customer or customer.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if name is not None:
        customer.name = name
    if allergies is not None:
        customer.allergies = allergies
    if preferences is not None:
        customer.preferences = preferences
    if preferred_language is not None:
        customer.preferred_language = preferred_language

    await session.flush()
    await session.commit()
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Anonimizar cliente (GDPR 'derecho al olvido') — no borra, vacía PII."""
    from uuid import UUID

    try:
        c_id = UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    customer = await session.get(Customer, c_id)
    if not customer or customer.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Anonimizar (patrón GDPR del panel)
    customer.name = None
    customer.phone = f"deleted-{customer.id}"
    customer.allergies = None
    customer.preferences = None
    customer.preferred_table_id = None

    await session.flush()
    await session.commit()
