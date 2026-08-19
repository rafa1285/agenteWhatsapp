"""Router REST de recordatorios (lectura + cancelación multi-tenant)."""

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.models import Restaurant
from app.modules.reminders.models import Reminder, ReminderStatus, ReminderType
from app.modules.reminders.schemas import ReminderInfo

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"], dependencies=[Depends(get_current_restaurant)])


@router.get("", response_model=list[ReminderInfo])
async def list_reminders(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[ReminderStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[ReminderType | None, Query(alias="type")] = None,
    date_from: Annotated[date_type | None, Query()] = None,
    date_to: Annotated[date_type | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReminderInfo]:
    """Listar recordatorios del restaurante con filtros opcionales."""
    from app.modules.reservations.models import Reservation

    stmt = (
        select(Reminder)
        .join(Reservation, Reminder.reservation_id == Reservation.id)
        .where(Reservation.restaurant_id == restaurant.id)
    )
    if status_filter:
        stmt = stmt.where(Reminder.status == status_filter)
    if type_filter:
        stmt = stmt.where(Reminder.type == type_filter)
    if date_from:
        stmt = stmt.where(Reminder.scheduled_send_at >= date_from)
    if date_to:
        stmt = stmt.where(Reminder.scheduled_send_at <= date_to)

    stmt = stmt.order_by(Reminder.scheduled_send_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{reminder_id}", response_model=ReminderInfo)
async def get_reminder(
    reminder_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReminderInfo:
    """Obtener recordatorio por ID (verifica tenant vía reservation)."""
    from uuid import UUID

    try:
        r_id = UUID(reminder_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    reminder = await session.get(Reminder, r_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")

    # Verificar que la reserva pertenece al tenant
    from app.modules.reservations.models import Reservation
    reservation = await session.get(Reservation, reminder.reservation_id)
    if not reservation or reservation.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")

    return reminder


@router.post("/{reminder_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reminder_endpoint(
    reminder_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Cancelar recordatorio pendiente."""
    from uuid import UUID

    try:
        r_id = UUID(reminder_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID inválido")

    reminder = await session.get(Reminder, r_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")

    # Verificar tenant
    from app.modules.reservations.models import Reservation
    reservation = await session.get(Reservation, reminder.reservation_id)
    if not reservation or reservation.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")

    if reminder.status != ReminderStatus.PENDING:
        raise HTTPException(status_code=409, detail="Solo se pueden cancelar recordatorios pendientes")

    reminder.status = ReminderStatus.CANCELLED
    await session.flush()
    await session.commit()
