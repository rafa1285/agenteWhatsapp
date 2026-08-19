"""Motor de recordatorios: programación del 24h y tick del worker.

- `schedule_24h_reminder` crea el recordatorio (PENDING, whatsapp) cuando la
  reserva pasa a confirmada; `_reservation_datetime_utc` convierte fecha/hora
  del restaurante a UTC y el envío se programa 24h antes.
- `process_due_reminders` es el tick: claim atómico de los PENDING vencidos
  (`FOR UPDATE SKIP LOCKED`, idempotente entre instancias del worker), verifica
  que la reserva sigue activa (§11), envía por WhatsApp y reintenta hasta
  `REMINDER_MAX_ATTEMPTS` (1 envío + reintentos) con retardo entre intentos.

Convenciones: los servicios hacen `flush` (nunca `commit`), salvo el tick, que
hace `commit` por recordatorio (no retener locks durante I/O de red). El worker
(no HTTP) es quien decide el límite de cada transacción.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from datetime import time as time_type
from uuid import UUID as uuid_UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp.gateway import WhatsAppGateway, WhatsAppSendError
from app.core.models import Restaurant
from app.core.settings import settings
from app.core.webhook import emit_reminder_event
from app.modules.customers.models import Customer
from app.modules.reminders.models import Reminder, ReminderChannel, ReminderStatus, ReminderType
from app.modules.reservations.models import ACTIVE_RESERVATION_STATUSES, Reservation

_WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def to_e164(phone: str) -> str:
    """Número a E.164 para la API de 360dialog.

    `Customer.phone` se guarda solo dígitos (`34611222333`); la API de WhatsApp
    exige el prefijo `+`. Si ya empieza por `+` se devuelve tal cual.
    """
    return phone if phone.startswith("+") else f"+{phone}"


def _format_date_es(value: date_type) -> str:
    return f"{_WEEKDAYS_ES[value.weekday()]}, {value.day} de {_MONTHS_ES[value.month - 1]}"


def build_reminder_text(
    *,
    restaurant_name: str,
    customer_name: str | None,
    date: date_type,
    time: time_type,
    party_size: int,
) -> str:
    """Texto del recordatorio 24h (español, idioma soportado por defecto).

    Pura (recibe primitivas) para testear sin tocar base de datos ni sesión.
    """
    greeting = f"¡Hola, {customer_name}!" if customer_name else "¡Hola!"
    people = "1 persona" if party_size == 1 else f"{party_size} personas"
    return (
        f"{greeting} Te recordamos tu reserva en {restaurant_name} para el "
        f"{_format_date_es(date)} a las {time.strftime('%H:%M')} para {people}."
    )


def _reservation_datetime_utc(reservation: Reservation, *, tz: str | None) -> datetime:
    """Fecha+hora de la reserva en el timezone del restaurante, convertida a UTC.

    `Reservation.date`/`time` son naive; se interpretan en `restaurant.timezone`.
    Un timezone inválido o ausente cae a UTC (defensivo, como en el canal de voz).
    """
    try:
        zone = ZoneInfo(tz) if tz else ZoneInfo("UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    local = datetime.combine(reservation.date, reservation.time, tzinfo=zone)
    return local.astimezone(UTC)


async def schedule_24h_reminder(
    session: AsyncSession,
    *,
    reservation: Reservation,
    restaurant: Restaurant,
) -> Reminder | None:
    """Programa el recordatorio 24h de la reserva (PENDING, whatsapp).

    Guard anti-duplicado: si ya existe un `24h_reminder` PENDING, no crea otro
    (protege los caminos create/confirm de una reserva que nace confirmada).
    Devuelve el recordatorio creado, o `None` si ya había uno.
    """
    existing = await session.scalar(
        select(Reminder).where(
            Reminder.reservation_id == reservation.id,
            Reminder.type == ReminderType.REMINDER_24H,
            Reminder.status == ReminderStatus.PENDING,
        )
    )
    if existing is not None:
        return None

    send_at = _reservation_datetime_utc(reservation, tz=restaurant.timezone) - timedelta(hours=24)
    reminder = Reminder(
        reservation_id=reservation.id,
        type=ReminderType.REMINDER_24H,
        status=ReminderStatus.PENDING,
        scheduled_send_at=send_at,
        channel=ReminderChannel.WHATSAPP,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def _process_one_reminder(
    session: AsyncSession,
    *,
    reminder: Reminder,
    gateway: WhatsAppGateway,
    now: datetime,
    max_attempts: int,
    retry_delay: timedelta,
) -> None:
    """Procesa un recordatorio ya reclamado. El caller commitea al terminar."""
    reservation = await session.get(Reservation, reminder.reservation_id)
    if reservation is None or reservation.status not in ACTIVE_RESERVATION_STATUSES:
        reminder.status = ReminderStatus.CANCELLED
        return
    if reservation.customer_id is None:
        reminder.status = ReminderStatus.CANCELLED
        return
    customer = await session.get(Customer, reservation.customer_id)
    if customer is None or not customer.phone:
        reminder.status = ReminderStatus.CANCELLED
        return

    restaurant = await session.get(Restaurant, reservation.restaurant_id)
    restaurant_name = restaurant.name if restaurant is not None else "tu restaurante"
    text = build_reminder_text(
        restaurant_name=restaurant_name,
        customer_name=customer.name,
        date=reservation.date,
        time=reservation.time,
        party_size=reservation.party_size,
    )
    try:
        await gateway.send_text(to=to_e164(customer.phone), text=text)
    except WhatsAppSendError:
        reminder.attempts += 1
        if reminder.attempts >= max_attempts:
            reminder.status = ReminderStatus.FAILED
        else:
            reminder.scheduled_send_at = now + retry_delay  # sigue PENDING, se re-programa
        await emit_reminder_event("reminder.failed", reminder)
        return
    reminder.status = ReminderStatus.SENT
    reminder.sent_at = now
    await emit_reminder_event("reminder.sent", reminder)


async def process_due_reminders(
    session: AsyncSession,
    *,
    gateway: WhatsAppGateway,
    now: datetime,
    batch_size: int | None = None,
) -> int:
    """Tick del worker: procesa los PENDING vencidos y devuelve cuántos.

    Claim atómico con `FOR UPDATE SKIP LOCKED` (idempotente entre instancias del
    worker) y `commit` por recordatorio: no se retienen locks durante el envío ni
    entre envíos. Si el proceso muere a mitad de un envío, la transacción se
    revierte y el recordatorio sigue PENDING (se vuelve a coger en otro tick).
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    max_attempts = settings.REMINDER_MAX_ATTEMPTS
    retry_delay = timedelta(seconds=settings.REMINDER_RETRY_DELAY_SECONDS)
    batch = batch_size if batch_size is not None else settings.REMINDER_BATCH_SIZE

    stmt = (
        select(Reminder)
        .where(Reminder.status == ReminderStatus.PENDING, Reminder.scheduled_send_at <= now)
        .order_by(Reminder.scheduled_send_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    reminders = list((await session.scalars(stmt)).all())

    processed = 0
    for reminder in reminders:
        await _process_one_reminder(
            session,
            reminder=reminder,
            gateway=gateway,
            now=now,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
        )
        await session.commit()
        processed += 1
    return processed


async def cancel_reminder(
    session: AsyncSession,
    *,
    reminder_id: uuid_UUID,
) -> Reminder | None:
    """Cancela un recordatorio PENDING (idempotente; ignora no-PENDING)."""
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None:
        return None
    if reminder.status == ReminderStatus.PENDING:
        reminder.status = ReminderStatus.CANCELLED
        await session.flush()
    return reminder


async def cancel_reminder_for_reservation(
    session: AsyncSession,
    *,
    reservation_id: uuid_UUID,
) -> int:
    """Cancela todos los recordatorios PENDING de una reserva (al cancelar la reserva)."""
    from sqlalchemy import update as sa_update

    result = await session.execute(
        sa_update(Reminder)
        .where(Reminder.reservation_id == reservation_id, Reminder.status == ReminderStatus.PENDING)
        .values(status=ReminderStatus.CANCELLED)
    )
    await session.flush()
    return result.rowcount
