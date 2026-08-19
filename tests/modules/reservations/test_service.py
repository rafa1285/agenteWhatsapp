"""Tests del motor de reservas (servicios puros, con base de datos)."""

import uuid
from datetime import UTC, date, datetime, time

import pytest
from app.agent.models import Escalation, EscalationReason
from app.modules.availability.schemas import AvailabilityReason
from app.modules.reminders.models import Reminder, ReminderChannel, ReminderStatus, ReminderType
from app.modules.reservations.exceptions import (
    ReservationConflictError,
    ReservationNotFoundError,
    ReservationUnavailableError,
    RestaurantNotFoundError,
)
from app.modules.reservations.models import AssignmentReason, ReservationStatus, SourceChannel
from app.modules.reservations.service import (
    cancel_reservation,
    check_in_reservation,
    confirm_reservation,
    create_reservation,
    mark_no_show,
    modify_reservation,
)
from sqlalchemy import func, select

SERVICE_DATE = date(2026, 9, 15)  # martes


async def test_create_confirmed_by_default(db_session, reservation_context):
    restaurant, customer, tables = await reservation_context()
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.CONFIRMED
    assert result.needs_escalation is False
    assert result.escalation_reason is None
    assert result.preferred_unavailable is False
    # Mejor ajuste para 2: la mesa de menor max_capacity que quepa (M1, max 4).
    assert result.reservation.table_id == tables[0].id
    assert result.reservation.assignment_reason is AssignmentReason.STANDARD_AVAILABILITY


async def test_large_group_pending_confirmation_with_escalation_signal(
    db_session, reservation_context
):
    restaurant, customer, _tables = await reservation_context(
        restaurant_overrides={"large_group_threshold": 8}, tables=((1, 12),)
    )
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=10,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.PENDING_CONFIRMATION
    assert result.needs_escalation is True
    assert result.escalation_reason is EscalationReason.LARGE_GROUP
    # La senal es para el orquestador: el servicio no crea la fila de Escalation.
    count = await db_session.scalar(select(func.count()).select_from(Escalation))
    assert count == 0


async def test_auto_confirm_disabled_creates_pending(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context(
        restaurant_overrides={"auto_confirm_enabled": False}
    )
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.PENDING_CONFIRMATION
    assert result.needs_escalation is False


async def test_no_show_risk_creates_pending(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context(
        customer_overrides={"no_show_count": 2}  # >= umbral por defecto (2)
    )
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.PENDING_CONFIRMATION


async def test_requires_prior_confirmation_creates_pending(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context(
        customer_overrides={"requires_prior_confirmation": True}
    )
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.PENDING_CONFIRMATION


async def test_create_raises_unavailable(db_session, reservation_context, reservation_factory):
    restaurant, customer, [table] = await reservation_context(tables=((1, 4),))
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=table.id,
        date=SERVICE_DATE,
        time=time(14, 0),
    )
    with pytest.raises(ReservationUnavailableError) as exc_info:
        await create_reservation(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            date=SERVICE_DATE,
            time=time(14, 0),
            party_size=2,
            source_channel=SourceChannel.WHATSAPP,
        )
    assert exc_info.value.reason is AvailabilityReason.NO_TABLE_FOR_PARTY
    assert exc_info.value.alternatives == []


async def test_confirm_transition_and_idempotent(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        status=ReservationStatus.PENDING,
    )
    confirmed = await confirm_reservation(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    assert confirmed.status is ReservationStatus.CONFIRMED
    again = await confirm_reservation(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    assert again.status is ReservationStatus.CONFIRMED


async def test_confirm_conflict_on_terminal(db_session, reservation_context, reservation_factory):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        status=ReservationStatus.CANCELLED,
    )
    with pytest.raises(ReservationConflictError):
        await confirm_reservation(
            db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
        )


async def test_check_in_completes_and_increments_once(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    completed = await check_in_reservation(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    assert completed.status is ReservationStatus.COMPLETED
    assert completed.checked_in_at is not None
    assert customer.visit_count == 1
    assert customer.last_visit is not None

    await check_in_reservation(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    assert customer.visit_count == 1  # idempotente: no se incrementa de nuevo


async def test_mark_no_show_increments_and_flips_threshold(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context(
        customer_overrides={"no_show_count": 1}  # con el incremento llega al umbral (2)
    )
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    no_show = await mark_no_show(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    assert no_show.status is ReservationStatus.NO_SHOW
    assert customer.no_show_count == 2
    assert customer.requires_prior_confirmation is True

    await mark_no_show(db_session, reservation_id=reservation.id, restaurant_id=restaurant.id)
    assert customer.no_show_count == 2  # idempotente


async def test_modify_reassigns_table_and_cancels_reminders(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context(tables=((1, 2), (1, 4)))
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time(14, 0),
    )
    # Ocupar la mesa pequena a las 15:00 para forzar el cambio de mesa.
    await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time(15, 0),
    )
    reminder = Reminder(
        reservation_id=reservation.id,
        type=ReminderType.REMINDER_24H,
        status=ReminderStatus.PENDING,
        scheduled_send_at=datetime(2026, 9, 15, 10, tzinfo=UTC),
        channel=ReminderChannel.WHATSAPP,
    )
    db_session.add(reminder)
    await db_session.flush()

    result = await modify_reservation(
        db_session,
        reservation_id=reservation.id,
        restaurant_id=restaurant.id,
        time=time(15, 0),
    )
    assert result.reassigned is True
    assert result.reservation.table_id == tables[1].id
    assert result.reservation.status is ReservationStatus.MODIFIED
    assert result.reservation.assignment_reason is AssignmentReason.STANDARD_AVAILABILITY
    assert reminder.status is ReminderStatus.CANCELLED


async def test_modify_notes_only_does_not_reassign(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    result = await modify_reservation(
        db_session,
        reservation_id=reservation.id,
        restaurant_id=restaurant.id,
        notes="ventana",
    )
    assert result.reassigned is False
    assert result.reservation.status is ReservationStatus.MODIFIED
    assert result.reservation.table_id == tables[0].id
    assert result.reservation.notes == "ventana"


async def test_cancel_cancels_pending_reminders(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    pending = Reminder(
        reservation_id=reservation.id,
        type=ReminderType.REMINDER_24H,
        status=ReminderStatus.PENDING,
        scheduled_send_at=datetime(2026, 9, 15, 10, tzinfo=UTC),
        channel=ReminderChannel.WHATSAPP,
    )
    sent = Reminder(
        reservation_id=reservation.id,
        type=ReminderType.POST_VISIT,
        status=ReminderStatus.SENT,
        scheduled_send_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
        channel=ReminderChannel.WHATSAPP,
    )
    db_session.add_all([pending, sent])
    await db_session.flush()

    cancelled = await cancel_reservation(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    assert cancelled.status is ReservationStatus.CANCELLED
    assert pending.status is ReminderStatus.CANCELLED
    assert sent.status is ReminderStatus.SENT

    # Idempotente sobre el estado terminal.
    await cancel_reservation(db_session, reservation_id=reservation.id, restaurant_id=restaurant.id)


async def test_reservation_invisible_across_tenants(
    db_session, reservation_context, restaurant_factory, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    other = await restaurant_factory()
    reservation = await reservation_factory(
        restaurant.id, customer_id=customer.id, table_id=tables[0].id, date=SERVICE_DATE
    )
    with pytest.raises(ReservationNotFoundError):
        await confirm_reservation(db_session, reservation_id=reservation.id, restaurant_id=other.id)


async def test_customer_of_other_tenant_conflict(
    db_session, reservation_context, restaurant_factory, customer_factory
):
    restaurant, _customer, _tables = await reservation_context()
    other = await restaurant_factory()
    other_customer = await customer_factory(other.id)
    with pytest.raises(ReservationConflictError):
        await create_reservation(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=other_customer.id,
            date=SERVICE_DATE,
            time=time(14, 0),
            party_size=2,
            source_channel=SourceChannel.WHATSAPP,
        )


async def test_create_raises_when_restaurant_not_found(db_session):
    with pytest.raises(RestaurantNotFoundError):
        await create_reservation(
            db_session,
            restaurant_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            date=SERVICE_DATE,
            time=time(14, 0),
            party_size=2,
            source_channel=SourceChannel.WHATSAPP,
        )


async def test_create_confirmed_schedules_24h_reminder(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context()
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.CONFIRMED
    reminder = await db_session.scalar(
        select(Reminder).where(Reminder.reservation_id == result.reservation.id)
    )
    assert reminder is not None
    assert reminder.type is ReminderType.REMINDER_24H
    assert reminder.status is ReminderStatus.PENDING
    assert reminder.channel is ReminderChannel.WHATSAPP
    # 14:00 CEST (septiembre, UTC+2) → 12:00 UTC, menos 24h.
    assert reminder.scheduled_send_at == datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


async def test_create_pending_confirmation_has_no_reminder_until_confirmed(
    db_session, reservation_context
):
    restaurant, customer, _tables = await reservation_context(
        restaurant_overrides={"auto_confirm_enabled": False}
    )
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    assert result.reservation.status is ReservationStatus.PENDING_CONFIRMATION
    count = await db_session.scalar(select(func.count()).select_from(Reminder))
    assert count == 0


async def test_confirm_schedules_24h_reminder(db_session, reservation_context, reservation_factory):
    restaurant, customer, tables = await reservation_context(
        restaurant_overrides={"auto_confirm_enabled": False}
    )
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        status=ReservationStatus.PENDING_CONFIRMATION,
    )
    await confirm_reservation(
        db_session, reservation_id=reservation.id, restaurant_id=restaurant.id
    )
    reminder = await db_session.scalar(
        select(Reminder).where(Reminder.reservation_id == reservation.id)
    )
    assert reminder is not None
    assert reminder.status is ReminderStatus.PENDING


async def test_modify_cancels_and_reschedules_24h_reminder(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time(14, 0),
    )
    reminder = Reminder(
        reservation_id=reservation.id,
        type=ReminderType.REMINDER_24H,
        status=ReminderStatus.PENDING,
        scheduled_send_at=datetime(2026, 9, 14, 12, tzinfo=UTC),
        channel=ReminderChannel.WHATSAPP,
    )
    db_session.add(reminder)
    await db_session.flush()

    result = await modify_reservation(
        db_session,
        reservation_id=reservation.id,
        restaurant_id=restaurant.id,
        time=time(15, 0),
    )

    assert result.reservation.status is ReservationStatus.MODIFIED
    assert reminder.status is ReminderStatus.CANCELLED
    new = await db_session.scalar(
        select(Reminder).where(
            Reminder.reservation_id == reservation.id, Reminder.status == ReminderStatus.PENDING
        )
    )
    assert new is not None
    assert new.id != reminder.id
    # Nueva hora 15:00 CEST → 13:00 UTC, menos 24h.
    assert new.scheduled_send_at == datetime(2026, 9, 14, 13, 0, tzinfo=UTC)


async def test_cancel_cancels_auto_scheduled_24h_reminder(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context()
    result = await create_reservation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        date=SERVICE_DATE,
        time=time(14, 0),
        party_size=2,
        source_channel=SourceChannel.WHATSAPP,
    )
    reminder = await db_session.scalar(
        select(Reminder).where(Reminder.reservation_id == result.reservation.id)
    )
    assert reminder is not None
    assert reminder.status is ReminderStatus.PENDING

    await cancel_reservation(
        db_session, reservation_id=result.reservation.id, restaurant_id=restaurant.id
    )

    row = await db_session.get(Reminder, reminder.id)
    assert row.status is ReminderStatus.CANCELLED
