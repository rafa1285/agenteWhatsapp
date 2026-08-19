"""Procesamiento de un mensaje entrante de WhatsApp (capa de transporte).

El handler es el corazón del e2e: resuelve tenant y cliente, registra el dedup,
retoma el transcript previo, delega en `run_conversation` y responde por la API
de 360dialog. El límite de transacción vive aquí: o se commitea todo
(conversación, reserva, escalación, cliente y fila de dedup) o nada (500 →
360dialog reintenta; el dedup garantiza "at-most-once"). Los servicios internos
solo hacen `flush`.
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.agent.models import ConversationChannel
from app.agent.orchestrator import run_conversation
from app.agent.service import latest_conversation_transcript
from app.channels.whatsapp.gateway import WhatsAppGateway, WhatsAppSendError
from app.channels.whatsapp.models import WebhookMessage
from app.channels.whatsapp.schemas import InboundMessage
from app.core.service import get_restaurant_by_whatsapp_number, mask_phone
from app.modules.customers.service import find_or_create_customer_by_phone
from app.modules.reservations.models import SourceChannel

logger = logging.getLogger(__name__)


async def process_whatsapp_message(
    session: AsyncSession,
    *,
    phone_number_id: str,
    message: InboundMessage,
    llm: LLMClient,
    gateway: WhatsAppGateway,
) -> str | None:
    """Procesa un mensaje y devuelve el texto de respuesta enviado, o `None` si se salta.

    Se salta (devuelve `None`, y el router responde 200) cuando: el número no
    pertenece a un restaurante activo, el mensaje ya fue procesado (dedup), o no
    tiene texto utilizable. Devuelve el texto aunque el envío falle (el mensaje
    ya está procesado y persistido); solo lo loguea.
    """
    inbound_text = message.text.body if message.text else None
    if not inbound_text:
        logger.info("mensaje WhatsApp sin texto (id=%s): ignorado", message.id)
        return None

    restaurant = await get_restaurant_by_whatsapp_number(
        session, whatsapp_number_id=phone_number_id
    )
    if restaurant is None:
        logger.info(
            "webhook WhatsApp para número desconocido/inactivo (%s): ignorado",
            phone_number_id,
        )
        return None

    customer = await find_or_create_customer_by_phone(
        session, restaurant_id=restaurant.id, phone=message.from_
    )

    # Dedup antes de procesar: el único (restaurant_id, wa_message_id) hace
    # "at-most-once" frente a las reentregas de 360dialog. Va DESPUÉS del
    # cliente: si el find-or-create hizo rollback por carrera, no se pierde.
    session.add(WebhookMessage(restaurant_id=restaurant.id, wa_message_id=message.id))
    try:
        await session.flush()
    except IntegrityError:
        # Duplicado entregado en secuencia: otro request ya commiteó este
        # message_id. El rollback solo descarta el cliente recién creado, si lo
        # hubo; el ganador ya commiteó el suyo.
        logger.info(
            "mensaje WhatsApp duplicado (id=%s, %s): ignorado",
            message.id,
            mask_phone(message.from_),
        )
        await session.rollback()
        return None

    prior_transcript = await latest_conversation_transcript(
        session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
    )

    result = await run_conversation(
        session,
        llm=llm,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message=inbound_text,
        customer_id=customer.id,
        prior_transcript=prior_transcript,
    )

    try:
        await session.commit()
    except IntegrityError:
        # Carrera paralela: otro request commiteó el mismo message_id justo
        # después de nuestro flush. Se descarta todo este procesado y se trata
        # como duplicado: at-most-once garantizado en el commit.
        logger.info(
            "mensaje WhatsApp en carrera (id=%s, %s): ignorado",
            message.id,
            mask_phone(message.from_),
        )
        await session.rollback()
        return None

    try:
        await gateway.send_text(to=message.from_, text=result.text)
    except WhatsAppSendError as exc:
        # El mensaje ya está procesado y persistido; sin outbox en esta fase.
        logger.warning("no se pudo enviar la respuesta a %s: %s", mask_phone(message.from_), exc)
    return result.text
