"""Tests del motor de recordatorios (helpers puros + programación del 24h)."""

from datetime import UTC, datetime
from datetime import date as date_type
from datetime import time as time_type

from app.modules.reminders.models import Reminder, ReminderChannel, ReminderStatus, ReminderType
from app.modules.reminders.service import (
    _reservation_datetime_utc,
    build_reminder_text,
    schedule_24h_reminder,
    to_e164,
)
from app.modules.reservations.models import Reservation
from sqlalchemy import func, select

SERVICE_DATE = date_type(2026, 9, 15)  # martes


def test_to_e164_prefixes_digits_with_plus() -> None:
    assert to_e164("34611222333") == "+34611222333"


def test_to_e164_keeps_existing_plus() -> None:
    assert to_e164("+34611222333") == "+34611222333"


def test_reservation_datetime_utc_madrid_summer() -> None:
    reservation = Reservation(date=SERVICE_DATE, time=time_type(14, 0))
    # Septiembre 2026 está en CEST (UTC+2): 14:00 local → 12:00 UTC.
    assert _reservation_datetime_utc(reservation, tz="Europe/Madrid") == datetime(
        2026, 9, 15, 12, 0, tzinfo=UTC
    )


def test_reservation_datetime_utc_invalid_tz_falls_back_to_utc() -> None:
    reservation = Reservation(date=SERVICE_DATE, time=time_type(14, 0))
    assert _reservation_datetime_utc(reservation, tz="Not/AZone") == datetime(
        2026, 9, 15, 14, 0, tzinfo=UTC
    )


def test_build_reminder_text_includes_restaurant_date_time_and_party() -> None:
    text = build_reminder_text(
        restaurant_name="Er Pichi",
        customer_name="Ana",
        date=SERVICE_DATE,
        time=time_type(14, 0),
        party_size=2,
    )
    assert "Er Pichi" in text
    assert "martes, 15 de septiembre" in text
    assert "14:00" in text
    assert "2 personas" in text


def test_build_reminder_text_generic_greeting_without_name() -> None:
    text = build_reminder_text(
        restaurant_name="Er Pichi",
        customer_name=None,
        date=SERVICE_DATE,
        time=time_type(14, 0),
        party_size=2,
    )
    assert text.startswith("¡Hola! Te recordamos")


def test_build_reminder_text_singular_person() -> None:
    text = build_reminder_text(
        restaurant_name="Er Pichi",
        customer_name="Ana",
        date=SERVICE_DATE,
        time=time_type(14, 0),
        party_size=1,
    )
    assert "1 persona" in text


async def test_schedule_24h_reminder_creates_pending_whatsapp(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time_type(14, 0),
    )

    reminder = await schedule_24h_reminder(
        db_session, reservation=reservation, restaurant=restaurant
    )

    assert reminder is not None
    assert reminder.reservation_id == reservation.id
    assert reminder.type is ReminderType.REMINDER_24H
    assert reminder.status is ReminderStatus.PENDING
    assert reminder.channel is ReminderChannel.WHATSAPP
    assert reminder.attempts == 0
    # 14:00 CEST → 12:00 UTC; el recordatorio se programa 24h antes.
    assert reminder.scheduled_send_at == datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


async def test_schedule_24h_reminder_deduplicates(
    db_session, reservation_context, reservation_factory
):
    restaurant, customer, tables = await reservation_context()
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id,
        table_id=tables[0].id,
        date=SERVICE_DATE,
        time=time_type(14, 0),
    )

    first = await schedule_24h_reminder(db_session, reservation=reservation, restaurant=restaurant)
    second = await schedule_24h_reminder(db_session, reservation=reservation, restaurant=restaurant)

    assert first is not None
    assert second is None
    count = await db_session.scalar(select(func.count()).select_from(Reminder))
    assert count == 1
