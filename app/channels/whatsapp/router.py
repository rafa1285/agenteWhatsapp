"""Router del webhook de WhatsApp (360dialog): verificación y recepción.

Solo capa de transporte: parsea el payload, resuelve tenant/cliente, delega en
`process_whatsapp_message` y responde 200. Los mensajes que no requieren acción
(statuses, duplicados, número desconocido) también responden 200: un no-2xx haría
que 360dialog reintentara y eso es justo lo que el dedup evita.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.channels.whatsapp.dependencies import get_llm_client, get_whatsapp_gateway
from app.channels.whatsapp.gateway import WhatsAppGateway
from app.channels.whatsapp.handler import process_whatsapp_message
from app.channels.whatsapp.schemas import WebhookPayload
from app.core.settings import settings
from app.db.session import get_db_session

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.get("/webhook")
async def verify_webhook(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """Handshake de verificación que exige 360dialog al dar de alta el webhook.

    Si el token coincide con `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, se responde 200 con
    el `challenge` en texto plano; si no, 403. El token por defecto ("cambia-me")
    es solo para desarrollo: producción debe fijarlo en `.env`.
    """
    if (
        hub_mode == "subscribe"
        and hub_verify_token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        and hub_challenge
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def receive_webhook(
    payload: WebhookPayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
) -> dict:
    """Recibe el payload de 360dialog y lo procesa inline (síncrono).

    Devuelve 200 siempre que no haya un error de programación: un payload sin
    mensajes útiles se ignora; un fallo real del procesado se propaga como 500
    y 360dialog reintenta, pero el dedup evita dobles efectos.
    """
    inbound = payload.inbound()
    if inbound is None:
        # Solo statuses, mensajes sin texto o sin metadatos: nada que atender.
        return {"status": "ignored"}
    phone_number_id, message = inbound
    await process_whatsapp_message(
        session,
        phone_number_id=phone_number_id,
        message=message,
        llm=llm,
        gateway=gateway,
    )
    return {"status": "ok"}
