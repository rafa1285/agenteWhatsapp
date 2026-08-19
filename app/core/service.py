"""Servicios de la capa core: resolución de tenant y configuración.

Solo queries puras (sin dependencia HTTP); reutilizables por los canales
(webhook de WhatsApp, voz), el panel y el agente.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Restaurant


async def get_restaurant_by_whatsapp_number(
    session: AsyncSession, *, whatsapp_number_id: str
) -> Restaurant | None:
    """Resuelve el tenant activo cuyo número de WhatsApp Business coincide.

    Es el punto de aislamiento del webhook: un payload cuyo `phone_number_id`
    no pertenezca a un restaurante activo se descarta (devuelve `None`) sin
    procesar.
    """
    result = await session.scalar(
        select(Restaurant).where(
            Restaurant.whatsapp_number_id == whatsapp_number_id,
            Restaurant.active.is_(True),
        )
    )
    return result


async def get_restaurant_by_voice_number(
    session: AsyncSession, *, voice_number: str
) -> Restaurant | None:
    """Resuelve el tenant activo cuyo número de voz (Twilio `To`) coincide.

    Espejo de `get_restaurant_by_whatsapp_number` para el webhook de voz: una
    llamada cuyo `To` no pertenezca a un restaurante activo recibe un TwiML de
    cortesía y se descarta sin procesar.
    """
    result = await session.scalar(
        select(Restaurant).where(
            Restaurant.voice_number == voice_number,
            Restaurant.active.is_(True),
        )
    )
    return result


def mask_phone(phone: str) -> str:
    """Enmascara un teléfono para logs (PII): conserva 3 últimos dígitos."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) <= 3:
        return "***"
    return f"***{digits[-3:]}"
