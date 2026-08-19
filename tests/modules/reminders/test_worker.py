"""Tests del tick del worker (`process_due_reminders`), sin red.

El tick recibe `now` explícito (determinista): los tests fijan un instante y
programan los recordatorios relativo a él. El gateway es `FakeWhatsAppGateway`
o un gateway que lanza `WhatsAppSendError` (reintentos).
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from datetime import time as time_type

from app.channels.whatsapp.gateway import FakeWhatsAppGateway, WhatsAppSendError
from app.modules.reminders.models import Reminder, ReminderStatus
from app.modules.reminders.service import process_due_reminders, to_e164
from app.modules.reservations.models import ReservationStatus
from sqlalchemy import select

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
DUE_AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)  # recordatorio 24h de una reserva 14:00 UTC+2
_UNSET = object()  # distingue "no pasado" de `customer_id=None` explícito


class _FailingGateway:
    """Envío que siempre lanza `WhatsAppSendError` (para testear reintentos)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_text(self, *, to: str, text: str) -> None:
        self.sent.append({"to": to, "text": text})
        raise WhatsAppSendError("no hay red")


async def _setup(
    *,
    reservation_context,
    reservation_factory,
    reminder_factory,
    restaurant_overrides=None,
    customer_id=_UNSET,
    status=ReservationStatus.CONFIRMED,
    scheduled=DUE_AT,
    attempts=0,
):
    """Restaurante + cliente + reserva + recordatorio vencido (por defecto)."""
    restaurant, customer, tables = await reservation_context(
        restaurant_overrides=restaurant_overrides or {}
    )
    reservation = await reservation_factory(
        restaurant.id,
        customer_id=customer.id if customer_id is _UNSET else customer_id,
        table_id=tables[0].id,
        date=date_type(2026, 9, 15),
        time=time_type(14, 0),
        status=status,
    )
    reminder = await reminder_factory(
        reservation.id, scheduled_send_at=scheduled, attempts=attempts
    )
    return restaurant, customer, reservation, reminder


async def _row(db_session, reminder: Reminder) -> Reminder:
    return await db_session.get(Reminder, reminder.id)


async def test_due_reminder_is_sent(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    restaurant, customer, _reservation, reminder = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
    )
    gateway = FakeWhatsAppGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 1
    row = await _row(db_session, reminder)
    assert row.status is ReminderStatus.SENT
    assert row.sent_at == NOW
    assert len(gateway.sent) == 1
    assert gateway.sent[0]["to"] == to_e164(customer.phone)
    assert restaurant.name in gateway.sent[0]["text"]
    assert "15 de septiembre" in gateway.sent[0]["text"]


async def test_not_yet_due_is_not_sent(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    _restaurant, _customer, _reservation, reminder = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        scheduled=NOW + timedelta(hours=1),
    )
    gateway = FakeWhatsAppGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 0
    row = await _row(db_session, reminder)
    assert row.status is ReminderStatus.PENDING
    assert gateway.sent == []


async def test_inactive_reservation_cancels_reminder(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    _restaurant, _customer, _reservation, reminder = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        status=ReservationStatus.CANCELLED,
    )
    gateway = FakeWhatsAppGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 1
    row = await _row(db_session, reminder)
    assert row.status is ReminderStatus.CANCELLED
    assert gateway.sent == []


async def test_reminder_without_customer_is_cancelled(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    _restaurant, _customer, _reservation, reminder = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        customer_id=None,
    )
    gateway = FakeWhatsAppGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 1
    row = await _row(db_session, reminder)
    assert row.status is ReminderStatus.CANCELLED
    assert gateway.sent == []


async def test_send_failure_reschedules_within_attempt_limit(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    _restaurant, _customer, _reservation, reminder = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        attempts=0,
    )
    gateway = _FailingGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 1
    row = await _row(db_session, reminder)
    assert row.status is ReminderStatus.PENDING  # sigue pendiente: se re-programa
    assert row.attempts == 1
    assert row.scheduled_send_at == NOW + timedelta(seconds=300)
    assert len(gateway.sent) == 1  # el envío sí se intentó


async def test_send_failure_fails_after_max_attempts(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    _restaurant, _customer, _reservation, reminder = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        attempts=2,  # REMINDER_MAX_ATTEMPTS=3: un fallo más → FAILED
    )
    gateway = _FailingGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 1
    row = await _row(db_session, reminder)
    assert row.status is ReminderStatus.FAILED
    assert row.attempts == 3


async def test_multi_tenant_processes_each_with_own_message(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    restaurant_a, customer_a, _res_a, reminder_a = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        restaurant_overrides={"name": "Rest A"},
    )
    restaurant_b, customer_b, _res_b, reminder_b = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
        restaurant_overrides={"name": "Rest B"},
    )
    gateway = FakeWhatsAppGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW)

    assert processed == 2
    texts = {entry["to"]: entry["text"] for entry in gateway.sent}
    assert set(texts) == {to_e164(customer_a.phone), to_e164(customer_b.phone)}
    assert restaurant_a.name in texts[to_e164(customer_a.phone)]
    assert restaurant_b.name in texts[to_e164(customer_b.phone)]
    assert restaurant_b.name not in texts[to_e164(customer_a.phone)]
    assert (await _row(db_session, reminder_a)).status is ReminderStatus.SENT
    assert (await _row(db_session, reminder_b)).status is ReminderStatus.SENT


async def test_batch_size_limits_processing(
    db_session, reservation_context, reservation_factory, reminder_factory
):
    _restaurant_a, _customer_a, _res_a, _reminder_a = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
    )
    _restaurant_b, _customer_b, _res_b, _reminder_b = await _setup(
        reservation_context=reservation_context,
        reservation_factory=reservation_factory,
        reminder_factory=reminder_factory,
    )
    gateway = FakeWhatsAppGateway()

    processed = await process_due_reminders(db_session, gateway=gateway, now=NOW, batch_size=1)

    assert processed == 1
    rows = list(await db_session.scalars(select(Reminder)))
    assert sum(1 for r in rows if r.status is ReminderStatus.SENT) == 1
    assert sum(1 for r in rows if r.status is ReminderStatus.PENDING) == 1
    assert len(gateway.sent) == 1
