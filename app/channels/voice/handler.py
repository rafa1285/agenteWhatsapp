"""Procesamiento del webhook de voz (TwiML de Twilio): máquina de estados.

`process_voice_call` es el corazón del canal de voz: resuelve tenant y cliente,
registra la llamada (`voice_calls`, dedup + estado), delega cada turno hablado en
`run_conversation` y devuelve el TwiML que Twilio ejecuta (`<Say>` TTS,
`<Gather input="speech">` STT por turnos, `<Dial>` transferencia en vivo).
`process_voice_status` persiste el estado terminal que Twilio reporta por
callback. El límite de transacción vive aquí (un `commit` por request), como en
WhatsApp.

Flujos de la sección 10 que materializa: aviso de grabación RGPD al inicio
(transversal), silencios (~4s re-pregunta / ~8s cuelga y registra incompleta,
§10.3), baja confianza del STT → pedir repetición (§10.5), queja/escalada →
transferir si la ventana lo permite o despedir si no (§10.6), recurrente por
Caller ID (§10.7), fallo técnico conservando lo capturado (§10.8).
"""

import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.agent.models import ConversationChannel, ConversationOutcome
from app.agent.orchestrator import run_conversation
from app.agent.service import latest_conversation_transcript
from app.channels.voice.models import VoiceCall, VoiceCallStatus
from app.channels.voice.schemas import TwilioCallRequest
from app.channels.voice.service import is_within_transfer_hours
from app.channels.voice.twiml import build_response, connect_stream, dial, gather, hangup, say
from app.channels.whatsapp.gateway import WhatsAppGateway, WhatsAppSendError
from app.core.models import Restaurant
from app.core.service import get_restaurant_by_voice_number, mask_phone
from app.core.settings import settings
from app.modules.customers.service import find_or_create_customer_by_phone
from app.modules.reservations.models import SourceChannel

logger = logging.getLogger(__name__)

#: Mensajes de voz de los distintos flujos (sección 10 del spec).
COURTESY_TEXT = "Lo sentimos, este número no está operativo en este momento. Adiós."
REPROMPT_TEXT = "¿Sigues ahí? Hable cuando quiera."
SECOND_SILENCE_TEXT = "No te oigo. Puedes llamarme de nuevo cuando quieras. Adiós."
LOW_CONFIDENCE_TEXT = "Perdona, no te he entendido bien. ¿Puedes repetírmelo, por favor?"
TRANSFER_TEXT = "Un momento, te pongo con el equipo."
TRANSFER_FAILED_TEXT = (
    "No he podido contactar con el equipo ahora mismo. Te han dejado avisado y en "
    "breve te llamamos. Adiós."
)
TECHNICAL_FAILURE_TEXT = "Estamos teniendo un problema técnico. Disculpe."

#: Estados terminales del status callback de Twilio (los demás son no-op).
_TERMINAL_CALL_STATUSES = frozenset({"completed", "busy", "failed", "no-answer", "canceled"})


def greeting_text(restaurant_name: str) -> str:
    """Saludo de bienvenida con el aviso de grabación (RGPD, transversal de voz)."""
    return (
        f"Bienvenido a {restaurant_name}. Esta llamada puede ser grabada con fines "
        "de calidad y formación. Cuéntame, ¿en qué puedo ayudarte?"
    )


def _call_action_url() -> str:
    """URL absoluta a la que Twilio devuelve cada turno (Gather/Dial action)."""
    return f"{settings.VOICE_BASE_URL}/api/voice/call"


def _media_stream_url(call_sid: str) -> str:
    """URL del WebSocket de medios, derivada de `VOICE_BASE_URL`.

    Un solo origen de verdad para túnel/dominio: https -> wss y http -> ws. El
    `CallSid` va en la query para que el stream resuelva tenant y cliente desde
    `voice_calls`, sin repetir identificadores por la red.
    """
    base = settings.VOICE_BASE_URL.strip()
    if base.startswith("https://"):
        base = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        base = "ws://" + base.removeprefix("http://")
    return f"{base.rstrip('/')}/api/voice/stream?CallSid={quote(call_sid, safe='')}"


def _media_stream_twiml(call_sid: str) -> str:
    """TwiML de un Media Stream: `<Connect><Stream>` y `<Say>` de respaldo.

    El `<Say>` posterior solo suena si el WebSocket cae: mientras el stream vive,
    habla ElevenLabs. Sin él, un fallo del stream dejaría al cliente en silencio.
    """
    return build_response(
        connect_stream(_media_stream_url(call_sid)),
        say("Se ha cortado la línea. Vuelve a llamar, por favor. Adiós."),
    )


def _gather_turn() -> str:
    """Gather tras un turno del agente (STT del siguiente turno, barge-in)."""
    return gather(
        say("Hable"),
        action=_call_action_url(),
        speech_timeout=settings.VOICE_SILENCE_REPROMPT_SECONDS,
    )


def _re_prompt(speech_timeout: int) -> str:
    """Re-pregunta tras un silencio: «¿Sigues ahí?» + Gather."""
    return build_response(
        say(REPROMPT_TEXT),
        gather(say("Hable"), action=_call_action_url(), speech_timeout=speech_timeout),
    )


def _courtesy() -> str:
    """TwiML de cortesía para llamadas que no corresponden a un tenant activo."""
    return build_response(say(COURTESY_TEXT), hangup())


def _should_transfer(restaurant: Restaurant) -> bool:
    """¿Procede transferencia en vivo (§10.6): habilitada, con número y en horas?"""
    if not restaurant.live_transfer_enabled or not restaurant.transfer_phone:
        return False
    return is_within_transfer_hours(restaurant.transfer_hours, tz=restaurant.timezone)


async def _get_or_create_voice_call(
    session: AsyncSession,
    *,
    call_sid: str,
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> tuple[VoiceCall, bool, bool]:
    """Devuelve la fila de la llamada: (fila, ¿nueva?, ¿hubo carrera?).

    `call_sid` es único, pero en voz NO marca un turno duplicado: el mismo
    CallSid se repite en cada turno y en el status callback. Tras una carrera se
    relee la fila ganadora y se continúa (a diferencia de WhatsApp, que ignora).
    """
    existing = await session.scalar(select(VoiceCall).where(VoiceCall.call_sid == call_sid))
    if existing is not None:
        return existing, False, False
    row = VoiceCall(call_sid=call_sid, restaurant_id=restaurant_id, customer_id=customer_id)
    session.add(row)
    try:
        await session.flush()
        return row, True, False
    except IntegrityError:
        # Carrera: otro request creó el call_sid entre el select y el insert.
        await session.rollback()
        existing = await session.scalar(select(VoiceCall).where(VoiceCall.call_sid == call_sid))
        if existing is None:
            raise
        return existing, False, True


async def process_voice_call(
    session: AsyncSession,
    *,
    request: TwilioCallRequest,
    llm: LLMClient,
    gateway: WhatsAppGateway,
) -> str:
    """Procesa un POST al Voice URL y devuelve el TwiML que ejecuta Twilio.

    Distingue saludo (primera petición del CallSid) de turno por la creación de
    la fila `voice_calls`, no por el texto: un silencio también llega como POST
    con `SpeechResult` vacío.
    """
    if not request.call_sid:
        logger.info("webhook de voz sin CallSid: cortesía")
        return _courtesy()

    if request.dial_call_status:
        return await _handle_dial_completion(session, request=request)

    if not request.to:
        logger.info("webhook de voz sin número destino: cortesía")
        return _courtesy()
    restaurant = await get_restaurant_by_voice_number(session, voice_number=request.to)
    if restaurant is None:
        logger.info("llamada a número desconocido/inactivo (%s): cortesía", request.to)
        return _courtesy()
    # Capturado antes de cualquier rollback por carrera (expiraría el objeto y
    # acceder a sus atributos haría un lazy-load síncrono -> MissingGreenlet).
    restaurant_id = restaurant.id

    customer = None
    if request.from_:
        customer = await find_or_create_customer_by_phone(
            session, restaurant_id=restaurant_id, phone=request.from_
        )
    customer_id = customer.id if customer is not None else None

    voice_call, newly_created, raced = await _get_or_create_voice_call(
        session,
        call_sid=request.call_sid,
        restaurant_id=restaurant_id,
        customer_id=customer_id,
    )
    if raced:
        # El rollback de la carrera expiró los objetos y pudo descartar un
        # customer recién insertado (primer turno de un número nuevo en carrera).
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            return _courtesy()
        if request.from_:
            customer = await find_or_create_customer_by_phone(
                session, restaurant_id=restaurant_id, phone=request.from_
            )
            voice_call.customer_id = customer.id
            customer_id = customer.id

    if newly_created:
        # Saludo + aviso RGPD + primer Gather. El commit deja la fila visible a
        # los turnos siguientes (cada turno es un request HTTP distinto) y al
        # WebSocket de medios, que resuelve la llamada por CallSid.
        try:
            await session.commit()
        except IntegrityError:
            # Carrera: otro request creó la llamada justo antes del commit.
            await session.rollback()
            return _re_prompt(settings.VOICE_SILENCE_HANGUP_SECONDS)
        if settings.USE_MEDIA_STREAMS:
            # Voz en tiempo real: Twilio abre el Media Stream y el audio entra por
            # el WebSocket. El saludo lo pone ElevenLabs desde el stream, no <Say>.
            return _media_stream_twiml(request.call_sid)
        return build_response(
            say(greeting_text(restaurant.name)),
            gather(
                say("Hable"),
                action=_call_action_url(),
                speech_timeout=settings.VOICE_SILENCE_REPROMPT_SECONDS,
            ),
        )

    return await _process_turn(
        session,
        request=request,
        voice_call=voice_call,
        restaurant=restaurant,
        customer_id=customer_id,
        llm=llm,
        gateway=gateway,
    )


async def _process_turn(
    session: AsyncSession,
    *,
    request: TwilioCallRequest,
    voice_call: VoiceCall,
    restaurant: Restaurant,
    customer_id: uuid.UUID | None,
    llm: LLMClient,
    gateway: WhatsAppGateway,
) -> str:
    """Procesa un turno hablado: silencios, baja confianza o conversación real."""
    speech = request.speech_text
    if speech is None:
        # Silencio: 1º re-pregunta, 2º cuelga y registra la llamada incompleta (§10.3).
        if voice_call.silence_count >= 1:
            voice_call.status = VoiceCallStatus.INCOMPLETE
            voice_call.completed_at = datetime.now(UTC)
            await session.commit()
            return build_response(say(SECOND_SILENCE_TEXT), hangup())
        voice_call.silence_count = 1
        await session.commit()
        return _re_prompt(settings.VOICE_SILENCE_HANGUP_SECONDS)

    if (
        request.confidence is not None
        and request.confidence < settings.VOICE_STT_CONFIDENCE_THRESHOLD
    ):
        # Baja confianza del STT (§10.5): pedir repetición, sin tocar el LLM.
        return build_response(say(LOW_CONFIDENCE_TEXT), _gather_turn())

    # Turno normal: reinicia el contador de silencios y delega en el orquestador.
    voice_call.silence_count = 0
    prior_transcript = await latest_conversation_transcript(
        session,
        restaurant_id=restaurant.id,
        customer_id=customer_id,
        channel=ConversationChannel.VOICE,
        since=voice_call.created_at,
    )
    result = await run_conversation(
        session,
        llm=llm,
        restaurant=restaurant,
        source_channel=SourceChannel.VOICE,
        incoming_message=speech,
        customer_id=customer_id,
        prior_transcript=prior_transcript,
    )

    send_confirm = False
    if result.outcome == ConversationOutcome.RESERVATION_CREATED:
        # Reserva por voz + confirmación escrita tras colgar (§10.1).
        twiml = build_response(say(result.text), hangup())
        if not voice_call.confirmation_sent and request.from_:
            voice_call.confirmation_sent = True
            send_confirm = True
    elif result.outcome in (ConversationOutcome.COMPLAINT, ConversationOutcome.ESCALATED):
        if _should_transfer(restaurant):
            # Transferencia en vivo (§10.6); el retorno lo gestiona el <Dial>.
            twiml = build_response(
                say(TRANSFER_TEXT),
                dial(
                    restaurant.transfer_phone,
                    timeout=settings.VOICE_TRANSFER_DIAL_TIMEOUT,
                    action=_call_action_url(),
                ),
            )
        else:
            # El agente ya escaló: se despide con el mensaje que ha generado.
            twiml = build_response(say(result.text), hangup())
    else:  # QUERY: sigue la conversación con otro Gather.
        twiml = build_response(say(result.text), _gather_turn())

    try:
        await session.commit()
    except IntegrityError:
        # Backstop por carrera: se descarta este turno y se re-pregunta al cliente.
        await session.rollback()
        logger.info("turno de voz en carrera (call_sid=%s): re-prompt", request.call_sid)
        return _re_prompt(settings.VOICE_SILENCE_REPROMPT_SECONDS)

    if send_confirm:
        # Se envía al E.164 de Twilio (`From`), no a `customer.phone` (normalizado
        # a solo dígitos, inválido para la API de 360dialog).
        try:
            await gateway.send_text(to=request.from_, text=result.text)
        except WhatsAppSendError as exc:
            logger.warning(
                "no se pudo enviar la confirmación WhatsApp a %s: %s",
                mask_phone(request.from_),
                exc,
            )
    return twiml


async def _handle_dial_completion(session: AsyncSession, *, request: TwilioCallRequest) -> str:
    """Retorno del `<Dial action>`: cierra el estado según cómo terminó la llamada.

    La escalación ya la creó el turno que disparó el Dial (outcome
    COMPLAINT/ESCALATED); aquí solo se registra el resultado de la transferencia.
    """
    voice_call = await session.scalar(
        select(VoiceCall).where(VoiceCall.call_sid == request.call_sid)
    )
    if voice_call is None:
        return _courtesy()
    if request.dial_call_status in ("answered", "completed"):
        voice_call.status = VoiceCallStatus.TRANSFERRED
        voice_call.completed_at = datetime.now(UTC)
        await session.commit()
        return build_response()  # Twilio ya gestiona la llamada transferida
    voice_call.status = VoiceCallStatus.INCOMPLETE
    voice_call.completed_at = datetime.now(UTC)
    await session.commit()
    return build_response(say(TRANSFER_FAILED_TEXT), hangup())


async def resolve_media_stream_call(
    session: AsyncSession, *, call_sid: str
) -> tuple[Restaurant, uuid.UUID | None] | None:
    """Resuelve tenant y cliente de un Media Stream a partir de su `CallSid`.

    La fila `voice_calls` la creó el primer POST del webhook, que además ya
    normalizó el número llamante en `customers`: el WebSocket no vuelve a
    resolver por teléfono ni inventa un tenant (una llamada de un número
    desconocido simplemente no llega aquí).
    """
    voice_call = await session.scalar(select(VoiceCall).where(VoiceCall.call_sid == call_sid))
    if voice_call is None:
        return None
    restaurant = await session.get(Restaurant, voice_call.restaurant_id)
    if restaurant is None:
        return None
    return restaurant, voice_call.customer_id


async def process_voice_status(session: AsyncSession, *, request: TwilioCallRequest) -> None:
    """Persiste el estado terminal de una llamada; los intermedios son no-op.

    Twilio llama al status callback en cada cambio de estado. Solo se persiste en
    los estados terminales: el callback no se adelanta al saludo (que incluye el
    aviso RGPD) ni crea la fila antes de tiempo.
    """
    if not request.call_sid or request.call_status not in _TERMINAL_CALL_STATUSES:
        return
    if not request.to:
        return
    restaurant = await get_restaurant_by_voice_number(session, voice_number=request.to)
    if restaurant is None:
        return
    voice_call, _newly, _raced = await _get_or_create_voice_call(
        session,
        call_sid=request.call_sid,
        restaurant_id=restaurant.id,
        customer_id=None,
    )
    if request.recording_url:
        voice_call.recording_url = request.recording_url
    if request.call_duration_seconds is not None:
        voice_call.call_duration = request.call_duration_seconds
    if voice_call.status == VoiceCallStatus.IN_PROGRESS:
        voice_call.status = (
            VoiceCallStatus.COMPLETED
            if request.call_status == "completed"
            else VoiceCallStatus.INCOMPLETE
        )
        voice_call.completed_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError:
        # Carrera: otro request creó/actualizó el mismo call_sid; se descarta.
        await session.rollback()
