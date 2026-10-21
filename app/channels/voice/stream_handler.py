"""Manejador de un Media Stream de Twilio (voz en tiempo real, §10).

Una instancia por llamada. El flujo, todo en streaming para no callar mientras el
modelo piensa:

    Twilio (μ-law 8 kHz) -> Deepgram -> turno cerrado -> orquestador en streaming
    -> frases -> ElevenLabs (μ-law 8 kHz) -> Twilio

Lo que aporta sobre el modo por turnos (`<Say>` + `<Gather>`):

- Habla frase a frase en cuanto el LLM la cierra, no cuando termina la respuesta.
- Barge-in: si el cliente interrumpe se manda `clear` a Twilio (vacía su búfer de
  audio) y se corta la síntesis en curso.
- Cierre ordenado: si falla el STT o el TTS se cierra el WebSocket y Twilio
  ejecuta el `<Say>` de respaldo que va detrás del `<Connect>`.

La transferencia en vivo (`<Dial>`) no existe aquí: dentro de un Media Stream
Twilio ya no ejecuta TwiML nuevo. La escalación deja su fila en `escalations` y
actúa el panel; el que transfiere sigue siendo el modo por turnos.
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import suppress
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.agent.models import ConversationOutcome
from app.agent.orchestrator import ConversationResult, run_conversation_stream
from app.channels.voice.handler import LOW_CONFIDENCE_TEXT, greeting_text
from app.channels.whatsapp.gateway import WhatsAppGateway, WhatsAppSendError
from app.core.models import Restaurant
from app.core.settings import settings
from app.core.stt import DeepgramStreamSTT
from app.core.tts import elevenlabs_tts_service
from app.modules.customers.models import Customer
from app.modules.reservations.models import SourceChannel

logger = logging.getLogger(__name__)

#: Una frase se habla en cuanto cierra un `.`/`!`/`?` con este mínimo de
#: caracteres: por debajo la voz suena entrecortada.
_MIN_SENTENCE_CHARS = 24
#: Si el modelo encadena sin cerrar frases, se corta igual: hablar pronto gana.
_MAX_SENTENCE_CHARS = 140


def split_first_sentence(buffer: str) -> tuple[str | None, str]:
    """Devuelve (primera frase cerrada, resto del búfer) o `(None, búfer)` si no hay.

    Se aplica sobre los deltas tal como van llegando, así que a veces el corte cae
    dentro de un número ("las 14.") : es el precio de hablar antes. El corte por
    longitud busca el último espacio para no partir una palabra.
    """
    for index, char in enumerate(buffer):
        if char not in ".!?" or index + 1 < _MIN_SENTENCE_CHARS:
            continue
        if index + 1 == len(buffer) or buffer[index + 1] in " \n\t":
            return buffer[: index + 1].strip(), buffer[index + 1 :].strip()
    if len(buffer) >= _MAX_SENTENCE_CHARS:
        cut = buffer.rfind(" ")
        cut = cut if cut > 0 else len(buffer)
        return buffer[:cut].strip(), buffer[cut:].strip()
    return None, buffer


class VoiceStreamHandler:
    """Un Media Stream de Twilio: audio entrante, turnos de conversación y audio saliente."""

    def __init__(
        self,
        *,
        websocket: WebSocket,
        session_factory: Callable[[], AsyncGenerator[AsyncSession, None]],
        llm: LLMClient,
        gateway: WhatsAppGateway,
        restaurant: Restaurant,
        customer_id: UUID | None = None,
    ) -> None:
        self._websocket = websocket
        self._session_factory = session_factory
        self._llm = llm
        self._gateway = gateway
        self._restaurant = restaurant
        self._customer_id = customer_id

        self._stream_sid: str | None = None
        self._caller: str | None = None
        self._stt: DeepgramStreamSTT | None = None
        self._speak_queue: asyncio.Queue[str] = asyncio.Queue()
        self._speak_task: asyncio.Task | None = None
        self._turn_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        #: Tareas de turno en vuelo (referencia fuerte para que el GC no las tire).
        self._turn_tasks: set[asyncio.Task] = set()
        #: Transcript JSON del orquestador: es la memoria entre turnos de la llamada.
        self._transcript: str | None = None
        self._speaking = False
        self._interrupted = False
        self._confirmation_sent = False
        self._closed = False

    # ----------------------------------------------------------------- entrada

    async def handle(self) -> None:
        """Atiende la llamada hasta que Twilio cierra el stream o falla un servicio."""
        self._speak_task = asyncio.create_task(self._speak_loop())
        try:
            async with DeepgramStreamSTT(
                on_transcript=self._on_transcript,
                on_speech_started=self._on_speech_started,
            ) as stt:
                self._stt = stt
                await self._read_loop()
        except Exception:
            # STT caído o loop reventado: mejor el `<Say>` de respaldo de Twilio
            # que dejar al cliente en silencio.
            logger.exception("Media Stream interrumpido: se cierra el WebSocket")
            await self._close_websocket()
        finally:
            self._stt = None
            await self._shutdown()

    # ------------------------------------------------------------------ Twilio

    async def _read_loop(self) -> None:
        """Consume los eventos del Media Stream hasta el `stop` o la desconexión."""
        while True:
            try:
                raw = await self._websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("evento de Media Stream sin JSON: %s", raw[:200])
                continue
            event = data.get("event")
            if event == "start":
                await self._on_start(data.get("start") or {})
            elif event == "media":
                await self._on_media(data.get("media") or {})
            elif event == "stop":
                logger.info("Twilio cerró el Media Stream (streamSid=%s)", self._stream_sid)
                return

    async def _on_start(self, start: dict) -> None:
        self._stream_sid = start.get("streamSid") or self._stream_sid
        self._caller = start.get("caller") or self._caller
        logger.info("Media Stream iniciado: streamSid=%s caller=%s", self._stream_sid, self._caller)
        if self._stream_sid is not None:
            # El saludo lo pone ElevenLabs aquí, no el `<Say>` del TwiML.
            await self._speak(greeting_text(self._restaurant.name))

    async def _on_media(self, media: dict) -> None:
        payload = media.get("payload")
        if not payload or self._stt is None:
            return
        await self._stt.send_audio(base64.b64decode(payload))

    async def _send(self, message: dict) -> None:
        """Escribe en el WebSocket con mutex: los eventos no pueden entrelazarse."""
        if self._closed:
            return
        async with self._send_lock:
            try:
                await self._websocket.send_text(json.dumps(message))
            except Exception:
                logger.info("el WebSocket de Twilio ya no acepta audio")
                self._closed = True

    async def _send_media(self, audio: bytes) -> None:
        if self._stream_sid is None:
            return
        await self._send(
            {
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": base64.b64encode(audio).decode("utf-8")},
            }
        )

    async def _send_clear(self) -> None:
        """Vacía el búfer de audio de Twilio: deja de oírse lo que ya se dijo."""
        if self._stream_sid is None:
            return
        await self._send({"event": "clear", "streamSid": self._stream_sid})

    async def _send_mark(self, name: str) -> None:
        if self._stream_sid is None:
            return
        await self._send({"event": "mark", "streamSid": self._stream_sid, "mark": {"name": name}})

    async def _close_websocket(self) -> None:
        self._closed = True
        try:
            await self._websocket.close()
        except Exception:
            logger.debug("el WebSocket de Twilio ya estaba cerrado", exc_info=True)

    # --------------------------------------------------------------- Deepgram

    async def _on_transcript(self, text: str, confidence: float) -> None:
        """Turno cerrado por Deepgram; se procesa en su propia tarea.

        Si se aguardara aquí quedaría bloqueado el despachador de eventos de
        Deepgram mientras piensa el modelo, y se perderían los `SpeechStarted`
        que producen el barge-in.
        """
        if confidence < settings.VOICE_STT_CONFIDENCE_THRESHOLD:
            logger.info("confianza baja (%.2f) en %r: se pide repetición", confidence, text)
            await self._speak(LOW_CONFIDENCE_TEXT)
            return
        # El turno va en su propia tarea y se guarda la referencia: sin ella el
        # event loop solo tiene una referencia débil y el GC puede tirarlo.
        task = asyncio.create_task(self._run_turn(text))
        self._turn_tasks.add(task)
        task.add_done_callback(self._turn_tasks.discard)

    async def _on_speech_started(self) -> None:
        """Barge-in: el cliente habla por encima del agente."""
        if not self._speaking:
            return
        logger.info("barge-in: se corta el audio en curso")
        self._interrupted = True
        await self._send_clear()
        while not self._speak_queue.empty():
            self._speak_queue.get_nowait()

    # ------------------------------------------------------------ conversación

    async def _run_turn(self, text: str) -> None:
        """Serializa los turnos: dos respuestas solapadas se pisarían al hablar."""
        if self._turn_lock.locked():
            logger.info("ya hay un turno en curso, se ignora %r", text)
            return
        async with self._turn_lock:
            await self._process_turn(text)

    async def _process_turn(self, text: str) -> None:
        started = time.perf_counter()
        buffer = ""
        result: ConversationResult | None = None
        try:
            async for session in self._session_factory():
                async for delta, turn_result in run_conversation_stream(
                    session,
                    llm=self._llm,
                    restaurant=self._restaurant,
                    source_channel=SourceChannel.VOICE,
                    incoming_message=text,
                    customer_id=self._customer_id,
                    prior_transcript=self._transcript,
                ):
                    if turn_result is not None:
                        result = turn_result
                    if not delta:
                        continue
                    buffer += delta
                    sentence, buffer = split_first_sentence(buffer)
                    while sentence:
                        logger.info(
                            "primera frase a los %.0f ms: %s",
                            (time.perf_counter() - started) * 1000,
                            sentence,
                        )
                        await self._speak(sentence)
                        sentence, buffer = split_first_sentence(buffer)
                if buffer.strip():
                    await self._speak(buffer.strip())
                if result is None:
                    logger.error("run_conversation_stream no devolvió ConversationResult")
                    return
                # La memoria de la llamada es el transcript del orquestador, en el
                # mismo formato que usa el modo por turnos.
                self._transcript = result.transcript
                await session.commit()
                await self._after_turn(result)
                break
        except Exception:
            logger.exception("fallo procesando el turno de voz %r", text)
            await self._speak(
                "Estoy teniendo un problema técnico. Te llamamos nosotros en un momento."
            )

    async def _after_turn(self, result: ConversationResult) -> None:
        """Confirmación escrita tras una reserva hecha por voz (§10.1)."""
        if result.outcome != ConversationOutcome.RESERVATION_CREATED:
            return
        if self._confirmation_sent:
            return
        # El evento `start` del Media Stream no trae el número llamante, así que
        # el destino se saca del cliente ya resuelto por el webhook.
        to = self._caller or await self._customer_phone()
        if not to:
            logger.warning("reserva por voz sin número al que enviar la confirmación")
            return
        self._confirmation_sent = True
        try:
            await self._gateway.send_text(to=to, text=result.text)
            logger.info("confirmación de reserva enviada por WhatsApp a %s", to)
        except WhatsAppSendError as exc:
            logger.warning("no se pudo enviar la confirmación por WhatsApp: %s", exc)

    async def _customer_phone(self) -> str | None:
        if self._customer_id is None:
            return None
        async for session in self._session_factory():
            return await session.scalar(
                select(Customer.phone).where(Customer.id == self._customer_id)
            )
        return None

    # ---------------------------------------------------------------------- TTS

    async def _speak(self, text: str) -> None:
        """Encola una frase; el consumidor la sintetiza cuando le toca."""
        cleaned = text.strip()
        if not cleaned:
            return
        # Encolar una frase anula la orden de cortar: el barge-in ya terminó.
        self._interrupted = False
        await self._speak_queue.put(cleaned)

    async def _speak_loop(self) -> None:
        while True:
            text = await self._speak_queue.get()
            await self._synthesize(text)

    async def _synthesize(self, text: str) -> None:
        """ElevenLabs -> chunks μ-law -> Twilio, cortando al primer barge-in."""
        if self._stream_sid is None or self._closed:
            logger.warning("sin Media Stream activo: no se puede hablar (%r)", text[:60])
            return
        self._speaking = True
        await self._send_mark("speech_start")
        started = time.perf_counter()
        first_chunk = True
        try:
            async for chunk in elevenlabs_tts_service.text_to_speech_stream(text):
                if self._interrupted:
                    logger.info(
                        "síntesis cortada por barge-in a los %.0f ms",
                        (time.perf_counter() - started) * 1000,
                    )
                    return
                if first_chunk:
                    first_chunk = False
                    logger.info(
                        "primer byte de audio a los %.0f ms de la síntesis",
                        (time.perf_counter() - started) * 1000,
                    )
                await self._send_media(chunk)
        except Exception:
            # Sin TTS no hay conversación: cerrar hace que Twilio ejecute su
            # `<Say>` de respaldo y la llamada no quede en silencio.
            logger.exception("ElevenLabs falló: se cierra el stream")
            await self._close_websocket()
        finally:
            self._speaking = False
            await self._send_mark("speech_end")

    # ------------------------------------------------------------------ cleanup

    async def _shutdown(self) -> None:
        """Suelta consumidor de audio y turnos en vuelo; Deepgram ya cerró su sesión."""
        for task in {self._speak_task, *self._turn_tasks}:
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._speak_task = None
        self._turn_tasks.clear()
