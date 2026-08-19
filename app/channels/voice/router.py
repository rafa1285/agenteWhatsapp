"""Router del webhook de voz (Twilio): Voice URL y status callback.

Solo capa de transporte: parsea el form-encoded, delega en `process_voice_call` /
`process_voice_status` y devuelve TwiML (XML). Cualquier fallo no controlado se
mapea a un `<Say>` de fallo técnico (§10.8) + cuelga: nunca un 500, que haría
que Twilio reintentara el webhook en bucle.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.channels.voice.dependencies import get_llm_client, get_whatsapp_gateway
from app.channels.voice.handler import (
    TECHNICAL_FAILURE_TEXT,
    process_voice_call,
    process_voice_status,
)
from app.channels.voice.schemas import TwilioCallRequest
from app.channels.voice.twiml import build_response, hangup, say
from app.channels.whatsapp.gateway import WhatsAppGateway
from app.db.session import get_db_session

router = APIRouter(prefix="/api/voice", tags=["voice"])

logger = logging.getLogger(__name__)


@router.post("/call")
async def receive_call(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
) -> Response:
    """Voice URL de Twilio: devuelve el TwiML del turno (o del saludo)."""
    payload = TwilioCallRequest.from_form(await request.form())
    try:
        twiml = await process_voice_call(session, request=payload, llm=llm, gateway=gateway)
    except Exception:
        logger.exception("fallo no controlado en el webhook de voz")
        twiml = build_response(say(TECHNICAL_FAILURE_TEXT), hangup())
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def receive_status(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Status callback de Twilio: persiste el estado terminal de la llamada."""
    payload = TwilioCallRequest.from_form(await request.form())
    await process_voice_status(session, request=payload)
    return Response(status_code=200)
