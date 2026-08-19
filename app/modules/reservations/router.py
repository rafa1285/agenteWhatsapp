"""Router REST de reservas (CRUD multi-tenant, auth JWT).

Endpoints protegidos con `get_current_restaurant` (extrae tenant del JWT).
"""

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.models import Restaurant
from app.modules.reservations.models import Reservation, ReservationStatus
from app.modules.reservations.schemas import (
    CancelBookingInput,
    ReservationCreateInput,
    ReservationInfo,
    ReservationModifyInput,
)
from app.modules.reservations.service import (
    cancel_reservation,
    check_in_reservation,
    create_reservation,
    mark_no_show,
    modify_reservation,
)

router = APIRouter(prefix="/api/v1/reservations", tags=["reservations"], dependencies=[Depends(get_current_restaurant)])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ReservationInfo)
async def create_reservation_endpoint(
    input: ReservationCreateInput,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReservationInfo:
    """Crear reserva (panel u otro cliente autenticado)."""
    result = await create_reservation(
        session=session,
        restaurant_id=restaurant.id,
        customer_id=input.customer_id,
        date=input.date,
        time=input.time,
        party_size=input.party_size,
        source_channel=input.source_channel,
        preferred_zone=input.preferred_zone,
        requested_table_id=input.requested_table_id,
        notes=input.notes,
    )
    await session.commit()
    return result.reservation


@router.get("", response_model=list[ReservationInfo])
async def list_reservations(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    date_from: Annotated[date_type | None, Query()] = None,
    date_to: Annotated[date_type | None, Query()] = None,
    status_filter: Annotated[ReservationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReservationInfo]:
    """Listar reservas del restaurante con filtros opcionales."""
    from sqlalchemy import select

    stmt = select(Reservation).where(Reservation.restaurant_id == restaurant.id)
    if date_from:
        stmt = stmt.where(Reservation.date >= date_from)
    if date_to:
        stmt = stmt.where(Reservation.date <= date_to)
    if status_filter:
        stmt = stmt.where(Reservation.status == status_filter)
    stmt = stmt.order_by(Reservation.date, Reservation.time).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{reservation_id}", response_model=ReservationInfo)
async def get_reservation(
    reservation_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReservationInfo:
    """Obtener reserva por ID (verifica tenant)."""
    from uuid import UUID


    try:
        res_id = UUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    reservation = await session.get(Reservation, res_id)
    if not reservation or reservation.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    return reservation


@router.patch("/{reservation_id}", response_model=ReservationInfo)
async def modify_reservation_endpoint(
    reservation_id: str,
    input: ReservationModifyInput,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReservationInfo:
    """Modificar reserva (campos opcionales)."""
    from uuid import UUID

    from app.modules.reservations.exceptions import (
        ReservationConflictError,
        ReservationNotFoundError,
    )

    try:
        res_id = UUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    try:
        reservation = await modify_reservation(
            session=session,
            reservation_id=res_id,
            restaurant_id=restaurant.id,
            date=input.date,
            time=input.time,
            party_size=input.party_size,
            preferred_zone=input.preferred_zone,
            requested_table_id=input.requested_table_id,
            notes=input.notes,
        )
    except ReservationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ReservationConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return reservation


@router.post("/{reservation_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation_endpoint(
    reservation_id: str,
    input: CancelBookingInput,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Cancelar reserva (requiere confirmación explícita)."""
    from uuid import UUID

    from app.modules.reservations.exceptions import (
        ReservationConflictError,
        ReservationNotFoundError,
    )

    try:
        res_id = UUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    try:
        await cancel_reservation(
            session=session,
            reservation_id=res_id,
            restaurant_id=restaurant.id,
            confirmed=input.confirmed,
            reason=input.reason,
        )
    except ReservationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ReservationConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()


@router.post("/{reservation_id}/check-in", status_code=status.HTTP_204_NO_CONTENT)
async def check_in_reservation_endpoint(
    reservation_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Check-in (sentar) de una reserva confirmada."""
    from uuid import UUID

    from app.modules.reservations.exceptions import (
        ReservationConflictError,
        ReservationNotFoundError,
    )

    try:
        res_id = UUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    try:
        await check_in_reservation(
            session=session,
            reservation_id=res_id,
            restaurant_id=restaurant.id,
        )
    except ReservationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ReservationConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()


@router.post("/{reservation_id}/no-show", status_code=status.HTTP_204_NO_CONTENT)
async def no_show_reservation_endpoint(
    reservation_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Marcar reserva como no-show."""
    from uuid import UUID

    from app.modules.reservations.exceptions import (
        ReservationConflictError,
        ReservationNotFoundError,
    )

    try:
        res_id = UUID(reservation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    try:
        await mark_no_show(
            session=session,
            reservation_id=res_id,
            restaurant_id=restaurant.id,
        )
    except ReservationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ReservationConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
