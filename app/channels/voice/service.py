"""Lógica pura del canal de voz (sin dependencia HTTP ni de BD).

`is_within_transfer_hours` decide si la transferencia en vivo (§10.6) está
disponible ahora según la ventana horaria que configura el panel en
`Restaurant.transfer_hours` (JSONB). Convención del formato (la escribe el
panel Laravel):

    [{"weekday": 1, "start": "09:00", "end": "14:00"},
     {"weekday": 1, "start": "17:00", "end": "23:30"}]

- `weekday`: 0=lunes … 6=domingo (misma convención que `shifts.weekday`).
- `start`/`end`: `"HH:MM"` 24h. `start < end` → slot intra-día, intervalo
  semiabierto `[start, end)`. `start > end` → cruza medianoche (empieza el día
  `weekday` y termina en `weekday+1`): activo en `[start, 24:00)` o `[00:00, end)`
  de ese día.
- `null`/`[]`/entradas malformadas → nunca activo (devuelve `False`).
"""

from datetime import UTC, datetime
from datetime import time as time_type
from typing import Any
from zoneinfo import ZoneInfo


def is_within_transfer_hours(transfer_hours: Any, *, tz: str, now: datetime | None = None) -> bool:
    """¿Está activa la ventana de transferencia en vivo, en el timezone dado?

    Convierte `now` (o la hora actual UTC) al timezone del restaurante y comprueba
    si cae en algún slot. Un timezone inválido o no soportado nunca transfiere.
    """
    if not transfer_hours:
        return False
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    try:
        local = current.astimezone(ZoneInfo(tz))
    except Exception:
        return False
    weekday = local.weekday()
    current_time = local.time().replace(tzinfo=None)

    for slot in transfer_hours:
        if not isinstance(slot, dict):
            continue
        try:
            slot_weekday = int(slot["weekday"])
            start = time_type.fromisoformat(slot["start"])
            end = time_type.fromisoformat(slot["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= end:
            if slot_weekday == weekday and start <= current_time < end:
                return True
        else:
            # Slot que cruza medianoche: empieza el día `weekday` y acaba en `weekday+1`.
            if (slot_weekday == weekday and current_time >= start) or (
                slot_weekday == (weekday - 1) % 7 and current_time < end
            ):
                return True
    return False
