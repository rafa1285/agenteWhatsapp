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

from fastapi import APIRouter, Depends, Request, Response, WebSocket, WebSocketDisconnect
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
    resolve_media_stream_call,
)
from app.channels.voice.schemas import TwilioCallRequest
from app.channels.voice.stream_handler import VoiceStreamHandler
from app.channels.voice.twiml import build_response, hangup, say
from app.channels.whatsapp.gateway import WhatsAppGateway
from app.db.session import async_session_factory, get_db_session

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
    # Sin esta línea no hay forma de saber qué ejecutó Twilio cuando algo falla.
    logger.info("TwiML devuelto (CallSid=%s): %s", payload.call_sid, twiml)
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def receive_status(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Status callback de Twilio: persiste el estado terminal de la llamada."""
    form = await request.form()
    # Twilio explica aquí por qué abortó un verbo (p. ej. 31920 = el Media Stream
    # no hizo handshake). Se registra antes de validar la firma: un fallo de firma
    # también es información.
    logger.info(
        "STATUS CALLBACK - %s: code=%s msg=%s (CallSid=%s)",
        form.get("CallStatus"),
        form.get("CallErrorCode"),
        form.get("CallStatusMessage"),
        form.get("CallSid"),
    )
    if not validate_twilio_signature(request, form_data=form):
        logger.warning("firma Twilio inválida en /api/voice/status")
        return Response(status_code=200)
    payload = TwilioCallRequest.from_form(form)
    await process_voice_status(session, request=payload)
    return Response(status_code=200)


@router.websocket("/stream")
async def media_stream(
    websocket: WebSocket,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    gateway: Annotated[WhatsAppGateway, Depends(get_whatsapp_gateway)],
) -> None:
    """Media Stream de Twilio: audio en tiempo real con Deepgram y ElevenLabs.

    Solo llega aquí si `USE_MEDIA_STREAMS=true`, porque el TwiML del saludo es el
    que abre el `<Connect>`. La identidad (tenant y cliente) no se pasa por la
    URL: se resuelve desde `voice_calls` con el `CallSid`, que ya creó el webhook.
    """
    # cloudflared no reenvía el 101 a Twilio a menos que declare que el cuerpo no
    # está codificado: sin esta cabecera Twilio no abre el Media Stream y ejecuta el
    # `<Say>` de respaldo (issue 1465 de cloudflared; ngrok no lo necesita).
    await websocket.accept(headers=[(b"content-encoding", b"identity")])
    call_sid = websocket.query_params.get("CallSid")
    if not call_sid:
        logger.warning("Media Stream sin CallSid: se cierra el WebSocket")
        await websocket.close(code=4000)
        return

    # Sesión efímera: solo para resolver la llamada. La conversación usará una
    # sesión por turno, porque un Media Stream dura minutos.
    async with async_session_factory() as session:
        identity = await resolve_media_stream_call(session, call_sid=call_sid)
    if identity is None:
        logger.warning("Media Stream de una llamada desconocida (CallSid=%s)", call_sid)
        await websocket.close(code=4004)
        return
    restaurant, customer_id = identity

    handler = VoiceStreamHandler(
        websocket=websocket,
        session_factory=get_db_session,
        llm=llm,
        gateway=gateway,
        restaurant=restaurant,
        customer_id=customer_id,
    )
    try:
        await handler.handle()
    except WebSocketDisconnect:
        logger.info("Twilio desconectó el Media Stream (CallSid=%s)", call_sid)
    finally:
        logger.info("Media Stream terminado (CallSid=%s)", call_sid)
