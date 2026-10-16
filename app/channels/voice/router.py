"""Router del webhook de voz (Twilio): Voice URL, status callback, y WebSocket de medios.

Solo capa de transporte: parsea el form-encoded, delega en `process_voice_call` /
`process_voice_status` y devuelve TwiML (XML). Cualquier fallo no controlado se
mapea a un `<Say>` de fallo técnico (§10.8) + cuelga: nunca un 500, que haría
que Twilio reintentara el webhook en bucle.

El nuevo endpoint de WebSocket (`/stream`) maneja el flujo de medios en tiempo real
para STT con Deepgram y TTS con ElevenLabs.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.channels.voice.dependencies import (
    get_llm_client,
    get_whatsapp_gateway,
    validate_twilio_signature,
)
from app.channels.voice.handler import (
    COURTESY_TEXT,
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


def _unsigned_call_response() -> Response:
    """TwiML de cortesía si el webhook no viene firmado por Twilio."""
    return Response(
        content=build_response(say(COURTESY_TEXT), hangup()),
        media_type="application/xml",
    )


@router.post("/call")
async def receive_call(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
) -> Response:
    """Voice URL de Twilio: devuelve el TwiML del turno (o del saludo)."""
    form = await request.form()
    logger.info("WEBHOOK VOZ RECIBIDO - Form: %s", dict(form))
    if not validate_twilio_signature(request, form_data=form):
        logger.warning("firma Twilio inválida en /api/voice/call")
        return _unsigned_call_response()
    payload = TwilioCallRequest.from_form(form)
    logger.info(
        "WEBHOOK VOZ PAYLOAD - To: %s, From: %s, CallSid: %s",
        payload.to,
        payload.from_,
        payload.call_sid,
    )
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
    form = await request.form()
    if not validate_twilio_signature(request, form_data=form):
        logger.warning("firma Twilio inválida en /api/voice/status")
        return Response(status_code=200)
    payload = TwilioCallRequest.from_form(form)
    await process_voice_status(session, request=payload)
    return Response(status_code=200)


@router.websocket("/stream")
async def media_stream(
    websocket: WebSocket,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
):
    """
    WebSocket de medios para Twilio: maneja el flujo de audio bidireccional.
    Recibe audio del cliente, lo envía a Deepgram para STT,
    procesa con el LLM, convierte respuesta a audio con ElevenLabs,
    y envía el audio de vuelta a Twilio.
    """
    await websocket.accept()
    logger.info("WebSocket de medios conectado")

    # Extraer información de la llamada de los query parameters o headers
    # En una implementación real, esto vendría del mensaje de start de Twilio
    call_sid = websocket.query_params.get("CallSid")
    if not call_sid:
        # Intentar obtenerlo de los headers
        call_sid = websocket.headers.get("twilio-call-sid")

    # Para ahora, vamos a simplificar y asumir que podemos obtener el restaurante
    # de alguna manera. En producción, esto sería más complejo.
    # Por ahora, vamos a crear un manejador básico que necesitaremos refinar.

    try:
        # Importar el manejador de flujo
        from app.channels.voice.stream_handler import VoiceStreamHandler

        # Obtener restaurant_id de alguna manera (en producción, vendría de Twilio o de base de datos)
        # Por ahora, vamos a usar un placeholder - esto necesitará ser refinado
        restaurant_id = websocket.query_params.get("restaurant_id")
        if not restaurant_id:
            logger.warning("No se proporcionó restaurant_id en el WebSocket")
            await websocket.close(code=4000)
            return

        # Obtener la sesión de restaurante
        from sqlalchemy import select

        from app.core.models import Restaurant
        from app.db.session import get_db_session

        # Esto es simplificado - en producción necesitamos manejar esto mejor
        async for db_session in get_db_session():
            stmt = select(Restaurant).where(Restaurant.id == restaurant_id)
            result = await db_session.execute(stmt)
            restaurant = result.scalar_one_or_none()
            if not restaurant:
                logger.error("Restaurante no encontrado: %s", restaurant_id)
                await websocket.close(code=4004)
                return
            break

        # Obtener customer_id si está disponible
        customer_id = websocket.query_params.get("customer_id")

        # Crear y ejecutar el manejador de flujo
        handler = VoiceStreamHandler(
            websocket=websocket,
            session_factory=get_db_session,
            llm_client=llm,
            whatsapp_gateway=gateway,
            restaurant=restaurant,
            customer_id=customer_id,
        )
        await handler.handle()

    except Exception as e:
        logger.error("Error en WebSocket de medios: %s", e, exc_info=True)
        try:
            await websocket.close(code=4000)
        except:
            pass
    finally:
        logger.info("WebSocket de medios desconectado")
