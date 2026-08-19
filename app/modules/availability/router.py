"""Router REST de disponibilidad (mesas, turnos, consulta de disponibilidad)."""

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.models import Restaurant
from app.modules.availability.models import Shift, Table, TableZone
from app.modules.availability.schemas import (
    AvailabilityResult,
    CheckAvailabilityInput,
    ShiftInfo,
    TableInfo,
)
from app.modules.availability.service import check_availability

router = APIRouter(prefix="/api/v1/availability", tags=["availability"], dependencies=[Depends(get_current_restaurant)])


@router.post("/check", response_model=AvailabilityResult)
async def check_availability_endpoint(
    input: CheckAvailabilityInput,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AvailabilityResult:
    """Consultar disponibilidad para fecha/hora/party_size/zona."""
    return await check_availability(
        session=session,
        restaurant_id=restaurant.id,
        date=input.date,
        time=input.time,
        party_size=input.party_size,
        preferred_zone=input.preferred_zone,
    )


@router.get("/tables", response_model=list[TableInfo])
async def list_tables(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    zone: Annotated[TableZone | None, Query()] = None,
) -> list[TableInfo]:
    """Listar mesas del restaurante (opcionalmente filtradas por zona)."""
    from sqlalchemy import select

    stmt = select(Table).where(Table.restaurant_id == restaurant.id)
    if zone:
        stmt = stmt.where(Table.zone == zone)
    stmt = stmt.order_by(Table.name)
    result = await session.execute(stmt)
    tables = list(result.scalars().all())
    return [
        TableInfo(
            id=t.id,
            name=t.name,
            zone=t.zone,
            min_capacity=t.min_capacity,
            max_capacity=t.max_capacity,
        )
        for t in tables
    ]


@router.post("/tables", response_model=TableInfo, status_code=status.HTTP_201_CREATED)
async def create_table(
    name: Annotated[str, Query(min_length=1, max_length=60)],
    zone: Annotated[TableZone, Query()],
    min_capacity: Annotated[int, Query(ge=1)],
    max_capacity: Annotated[int, Query(ge=1)],
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    position_x: Annotated[float | None, Query()] = None,
    position_y: Annotated[float | None, Query()] = None,
) -> TableInfo:
    """Crear mesa nueva."""
    from decimal import Decimal

    if min_capacity > max_capacity:
        raise HTTPException(status_code=400, detail="min_capacity no puede ser mayor que max_capacity")

    table = Table(
        restaurant_id=restaurant.id,
        name=name,
        zone=zone,
        min_capacity=min_capacity,
        max_capacity=max_capacity,
        position_x=Decimal(str(position_x)) if position_x is not None else None,
        position_y=Decimal(str(position_y)) if position_y is not None else None,
    )
    session.add(table)
    await session.flush()
    await session.commit()
    return TableInfo(
        id=table.id,
        name=table.name,
        zone=table.zone,
        min_capacity=table.min_capacity,
        max_capacity=table.max_capacity,
    )


@router.patch("/tables/{table_id}", response_model=TableInfo)
async def update_table(
    table_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    name: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
    zone: Annotated[TableZone | None, Query()] = None,
    min_capacity: Annotated[int | None, Query(ge=1)] = None,
    max_capacity: Annotated[int | None, Query(ge=1)] = None,
    position_x: Annotated[float | None, Query()] = None,
    position_y: Annotated[float | None, Query()] = None,
) -> TableInfo:
    """Actualizar mesa (campos opcionales)."""
    from decimal import Decimal
    from uuid import UUID

    try:
        t_id = UUID(table_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    table = await session.get(Table, t_id)
    if not table or table.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")

    if name is not None:
        table.name = name
    if zone is not None:
        table.zone = zone
    if min_capacity is not None:
        table.min_capacity = min_capacity
    if max_capacity is not None:
        table.max_capacity = max_capacity
    if position_x is not None:
        table.position_x = Decimal(str(position_x))
    if position_y is not None:
        table.position_y = Decimal(str(position_y))

    if table.min_capacity > table.max_capacity:
        raise HTTPException(status_code=400, detail="min_capacity no puede ser mayor que max_capacity")

    await session.flush()
    await session.commit()
    return TableInfo(
        id=table.id,
        name=table.name,
        zone=table.zone,
        min_capacity=table.min_capacity,
        max_capacity=table.max_capacity,
    )


@router.delete("/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(
    table_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Eliminar mesa."""
    from uuid import UUID

    try:
        t_id = UUID(table_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    table = await session.get(Table, t_id)
    if not table or table.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")

    await session.delete(table)
    await session.flush()
    await session.commit()


@router.get("/shifts", response_model=list[ShiftInfo])
async def list_shifts(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ShiftInfo]:
    """Listar turnos del restaurante."""
    from sqlalchemy import select

    stmt = select(Shift).where(Shift.restaurant_id == restaurant.id).order_by(Shift.weekday, Shift.special_date)
    result = await session.execute(stmt)
    shifts = list(result.scalars().all())
    return [
        ShiftInfo(
            date=s.special_date or date_type(1970, 1, 1),  # placeholder para weekday
            start_time=s.start_time,
            end_time=s.end_time,
            duration_minutes=s.average_table_duration,
            max_capacity=s.max_capacity,
        )
        for s in shifts
    ]


@router.post("/shifts", response_model=ShiftInfo, status_code=status.HTTP_201_CREATED)
async def create_shift(
    start_time: Annotated[str, Query()],  # HH:MM
    end_time: Annotated[str, Query()],
    max_capacity: Annotated[int, Query(ge=1)],
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    weekday: Annotated[int | None, Query(ge=0, le=6)] = None,
    special_date: Annotated[date_type | None, Query()] = None,
    average_table_duration: Annotated[int, Query(ge=15)] = 90,
) -> ShiftInfo:
    """Crear turno nuevo (weekday XOR special_date)."""
    from datetime import time as time_type

    if (weekday is None) == (special_date is None):
        raise HTTPException(status_code=400, detail="Exactamente uno de weekday o special_date es requerido")

    try:
        st = time_type.fromisoformat(start_time)
        et = time_type.fromisoformat(end_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato hora inválido (HH:MM)")

    if st >= et:
        raise HTTPException(status_code=400, detail="start_time debe ser anterior a end_time")

    shift = Shift(
        restaurant_id=restaurant.id,
        weekday=weekday,
        special_date=special_date,
        start_time=st,
        end_time=et,
        average_table_duration=average_table_duration,
        max_capacity=max_capacity,
    )
    session.add(shift)
    await session.flush()
    await session.commit()
    return ShiftInfo(
        date=shift.special_date or date_type(1970, 1, 1),
        start_time=shift.start_time,
        end_time=shift.end_time,
        duration_minutes=shift.average_table_duration,
        max_capacity=shift.max_capacity,
    )
