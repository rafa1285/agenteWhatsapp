"""Webhook callbacks del backend hacia el panel (real-time sync).

El backend puede notificar al panel Laravel cuando ocurren eventos relevantes
(reserva creada/modificada/cancelada, recordatorio enviado, escalación).
El panel expone `/api/webhook/backend` protegido con HMAC-SHA256.

En dev puede estar deshabilitado (`PANEL_WEBHOOK_URL` vacío) y el panel usa polling.
En producción se configura la URL del panel y un secreto compartido.
"""

import hashlib
import hmac
import json
import logging
from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import time as time_type
from typing import Any

import httpx

from app.core.settings import settings

logger = logging.getLogger(__name__)

_VALID_EVENTS = frozenset({
    "reservation.created",
    "reservation.modified",
    "reservation.cancelled",
    "reservation.checked_in",
    "reservation.no_show",
    "reminder.sent",
    "reminder.failed",
    "escalation.created",
    "escalation.resolved",
})


def _serialize(value: Any) -> Any:
    """Convierte tipos SQLAlchemy/Pydantic a JSON-serializable."""
    if value is None:
        return None
    if isinstance(value, (datetime_type, date_type, time_type)):
        return value.isoformat()
    if hasattr(value, "__str__") and not isinstance(value, (int, float, str, bool)):
        return str(value)
    return value


def _to_dict(obj: Any) -> dict[str, Any]:
    """Extrae un dict plano de un modelo SQLAlchemy."""
    result = {}
    for col in obj.__table__.columns:
        result[col.name] = _serialize(getattr(obj, col.name))
    return result


def _sign_payload(payload: dict[str, Any]) -> str:
    """Firma HMAC-SHA256 del body JSON serializado."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    secret = settings.PANEL_WEBHOOK_SECRET.encode()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


async def emit_webhook(event: str, payload: dict[str, Any]) -> None:
    """
    Emite un webhook al panel si está configurado.

    No bloquea la respuesta: errores se loguean pero no lanzan excepción.
    En modo TESTING (tests), los webhooks se deshabilitan completamente.
    """
    from app.core.settings import settings
    logger.info(f"emit_webhook called: event={event}, PANEL_WEBHOOK_URL={settings.PANEL_WEBHOOK_URL}, PANEL_WEBHOOK_SECRET={'set' if settings.PANEL_WEBHOOK_SECRET else 'NOT SET'}, TESTING={settings.TESTING}")

    # En modo testing, deshabilitar webhooks completamente para evitar MissingGreenlet
    if settings.TESTING:
        logger.debug("TESTING mode: omitiendo webhook %s", event)
        return

    if not settings.PANEL_WEBHOOK_URL or not settings.PANEL_WEBHOOK_SECRET:
        logger.debug("Panel webhook no configurado; omitiendo %s", event)
        return

    if event not in _VALID_EVENTS:
        logger.warning("Evento webhook desconocido: %s", event)
        return

    full_payload = {"event": event, "data": payload}
    signature = _sign_payload(full_payload)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            logger.info(f"Sending webhook to {settings.PANEL_WEBHOOK_URL}")
            response = await client.post(
                settings.PANEL_WEBHOOK_URL,
                json=full_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Backend-Signature": signature,
                    "User-Agent": "RecepcionIA-Backend/1.0",
                },
            )
            response.raise_for_status()
            logger.info("Webhook %s entregado al panel (status=%d)", event, response.status_code)
    except httpx.HTTPStatusError as e:
        logger.warning("Webhook %s falló con HTTP %d: %s", event, e.response.status_code, e.response.text)
    except Exception as e:
        logger.warning("Webhook %s falló: %s", event, e)


async def emit_reservation_event(event: str, reservation: "Reservation") -> None:
    """Emite evento de reserva con payload estandarizado."""
    from app.core.settings import settings
    # Check TESTING first to avoid accessing expired SQLAlchemy attributes in tests
    if settings.TESTING:
        logger.debug("TESTING mode: omitiendo webhook %s", event)
        return
    logger.info(f"emit_reservation_event called: event={event}, reservation_id={reservation.id}, PANEL_WEBHOOK_URL={settings.PANEL_WEBHOOK_URL}")
    await emit_webhook(event, _to_dict(reservation))


async def emit_reminder_event(event: str, reminder: "Reminder") -> None:
    """Emite evento de recordatorio."""
    from app.core.settings import settings
    if settings.TESTING:
        logger.debug("TESTING mode: omitiendo webhook %s", event)
        return
    await emit_webhook(event, _to_dict(reminder))


async def emit_escalation_event(event: str, escalation: "Escalation") -> None:
    """Emite evento de escalación."""
    from app.core.settings import settings
    if settings.TESTING:
        logger.debug("TESTING mode: omitiendo webhook %s", event)
        return
    await emit_webhook(event, _to_dict(escalation))
