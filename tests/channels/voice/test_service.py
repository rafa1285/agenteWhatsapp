"""Tests de la ventana de transferencia en vivo (`is_within_transfer_hours`).

Deterministas: siempre se pasa `now` fijo con tz UTC. En septiembre, Madrid va
UTC+2, de modo que 10:00 UTC = 12:00 hora local. 2026-09-15 es martes
(`weekday` 1), 2026-09-16 miércoles (`weekday` 2) y 2026-09-17 jueves.
"""

from datetime import UTC, datetime

from app.channels.voice.service import is_within_transfer_hours

TZ = "Europe/Madrid"

#: Martes 09:00-14:00.
MARTES_MANANA = [{"weekday": 1, "start": "09:00", "end": "14:00"}]


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_no_schedule_never_transfers() -> None:
    assert is_within_transfer_hours(None, tz=TZ, now=_utc(2026, 9, 15, 10, 0)) is False
    assert is_within_transfer_hours([], tz=TZ, now=_utc(2026, 9, 15, 10, 0)) is False


def test_within_slot_transfers() -> None:
    # 10:00 UTC = 12:00 Madrid (martes) → dentro de [09:00, 14:00).
    assert is_within_transfer_hours(MARTES_MANANA, tz=TZ, now=_utc(2026, 9, 15, 10, 0)) is True


def test_outside_slot_does_not_transfer() -> None:
    # 16:00 UTC = 18:00 Madrid (martes) → fuera del slot.
    assert is_within_transfer_hours(MARTES_MANANA, tz=TZ, now=_utc(2026, 9, 15, 16, 0)) is False


def test_wrong_weekday_does_not_transfer() -> None:
    # 10:00 UTC = 12:00 Madrid, pero miércoles (weekday 2) → fuera.
    assert is_within_transfer_hours(MARTES_MANANA, tz=TZ, now=_utc(2026, 9, 16, 10, 0)) is False


def test_slot_boundary_end_is_exclusive() -> None:
    # 12:00 UTC = 14:00 Madrid (martes) → el extremo `end` queda fuera.
    assert is_within_transfer_hours(MARTES_MANANA, tz=TZ, now=_utc(2026, 9, 15, 12, 0)) is False


def test_timezone_conversion_rolls_over_midnight() -> None:
    # 22:00 UTC = 00:00 del miércoles en Madrid: el slot del martes ya no aplica.
    assert is_within_transfer_hours(MARTES_MANANA, tz=TZ, now=_utc(2026, 9, 15, 22, 0)) is False


def test_overnight_slot_spans_weekdays() -> None:
    # Slot que cruza medianoche: miércoles 22:00 → jueves 02:00 (hora local).
    schedule = [{"weekday": 2, "start": "22:00", "end": "02:00"}]
    # Miércoles 23:00 Madrid = 21:00 UTC del 16.
    assert is_within_transfer_hours(schedule, tz=TZ, now=_utc(2026, 9, 16, 21, 0)) is True
    # Jueves 01:00 Madrid = 23:00 UTC del 16 (mismo slot, día siguiente).
    assert is_within_transfer_hours(schedule, tz=TZ, now=_utc(2026, 9, 16, 23, 0)) is True
    # Jueves 03:00 Madrid = 01:00 UTC del 17 → fuera del slot.
    assert is_within_transfer_hours(schedule, tz=TZ, now=_utc(2026, 9, 17, 1, 0)) is False


def test_malformed_slots_are_ignored() -> None:
    schedule = [
        {"weekday": "x", "start": "09:00", "end": "14:00"},  # weekday inválido
        {"weekday": 1, "start": "mala", "end": "14:00"},  # hora inválida
        "no es un dict",
        {"start": "09:00", "end": "14:00"},  # sin weekday
        {"weekday": 1, "start": "09:00"},  # sin end
    ]
    assert is_within_transfer_hours(schedule, tz=TZ, now=_utc(2026, 9, 15, 10, 0)) is False


def test_invalid_timezone_never_transfers() -> None:
    assert (
        is_within_transfer_hours(MARTES_MANANA, tz="No/Existe", now=_utc(2026, 9, 15, 10, 0))
        is False
    )
