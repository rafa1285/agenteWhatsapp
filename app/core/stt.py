"""STT en tiempo real con Deepgram (SDK v7, WebSocket async).

Una conexión por llamada: el audio de un Media Stream de Twilio pertenece a un
CallSid, así que compartir un singleton entre llamadas mezclaría transcripciones.
El formato es μ-law 8 kHz, que es lo único que Twilio envía por el stream.

Configuración validada contra la API real: `nova-3` + `dictation` emite frases
definitivas con `speech_final`, pero rechaza `utterance_end_ms`, así que el
final de turno se decide en cliente (ver `_restart_flush`).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType

from app.core.settings import settings

logger = logging.getLogger(__name__)

#: Turno cerrado: (texto completo del turno, confianza de la última frase).
TranscriptCallback = Callable[[str, float], Awaitable[None]]
#: El usuario empezó a hablar (sirve para el barge-in sobre el TTS).
SpeechStartedCallback = Callable[[], Awaitable[None]]

_KEEPALIVE_INTERVAL_SECONDS = 8.0


class DeepgramStreamSTT:
    """Transcripción en directo de una llamada: `async with` abre y cierra la sesión."""

    def __init__(
        self,
        *,
        on_transcript: TranscriptCallback,
        on_speech_started: SpeechStartedCallback | None = None,
    ) -> None:
        self._client = AsyncDeepgramClient(api_key=settings.DEEPGRAM_API_KEY or None)
        self._on_transcript = on_transcript
        self._on_speech_started = on_speech_started
        self._connection = None
        self._context = None
        self._listening_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        #: Frases definitivas (`speech_final`) del turno en curso.
        self._segments: list[str] = []
        self._confidence = 0.0
        #: Último texto (parcial o definitivo) visto: red de seguridad si el
        #: turno termina sin ningún `speech_final`.
        self._last_text = ""

    async def __aenter__(self) -> "DeepgramStreamSTT":
        self._context = self._client.listen.v1.connect(
            model=settings.VOICE_STT_MODEL,
            language=settings.VOICE_STT_LANGUAGE,
            encoding="mulaw",
            sample_rate=8000,
            interim_results=True,
            dictation=True,
            vad_events=True,
            smart_format=True,
        )
        self._connection = await self._context.__aenter__()
        self._connection.on(EventType.MESSAGE, self._handle_message)
        self._connection.on(EventType.ERROR, self._handle_error)
        self._listening_task = asyncio.create_task(self._connection.start_listening())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info(
            "Deepgram conectado (modelo %s, idioma %s)",
            settings.VOICE_STT_MODEL,
            settings.VOICE_STT_LANGUAGE,
        )
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        self._cancel_flush()
        for task in (self._keepalive_task, self._listening_task):
            if task is not None:
                task.cancel()
        self._keepalive_task = None
        self._listening_task = None
        if self._connection is not None and self._context is not None:
            try:
                await self._connection.send_close_stream()
            except Exception:
                logger.debug("enviar close_stream a Deepgram falló", exc_info=True)
            try:
                await self._context.__aexit__(None, None, None)
            except Exception:
                logger.debug("cerrando el contexto de Deepgram", exc_info=True)
        self._connection = None
        self._context = None

    async def send_audio(self, audio: bytes) -> None:
        """Envía un chunk de μ-law 8 kHz al WebSocket de Deepgram."""
        if self._connection is None:
            return
        await self._connection.send_media(audio)

    async def _keepalive_loop(self) -> None:
        # Deepgram cierra el socket tras ~10 s sin frames de media ni keep-alive;
        # en silencios largos del usuario hay que mantenerlo vivo.
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL_SECONDS)
            if self._connection is None:
                return
            try:
                await self._connection.send_keep_alive()
            except Exception:
                logger.debug("keep-alive de Deepgram falló", exc_info=True)
                return

    async def _handle_error(self, error) -> None:
        logger.error("Error de Deepgram: %s", error)

    async def _handle_message(self, message) -> None:
        kind = getattr(message, "type", None)
        if kind == "Results":
            await self._handle_results(message)
        elif kind == "UtteranceEnd":
            await self._emit_turn(source="utterance_end")
        elif kind == "SpeechStarted":
            # Habla en curso: no cerrar el turno mientras llega.
            self._cancel_flush()
            if self._on_speech_started is not None:
                await self._on_speech_started()

    async def _handle_results(self, results) -> None:
        alternatives = getattr(getattr(results, "channel", None), "alternatives", None) or []
        if not alternatives:
            return
        text = (alternatives[0].transcript or "").strip()
        confidence = float(alternatives[0].confidence or 0.0)
        if not text and not getattr(results, "speech_final", False):
            return

        self._last_text = text or self._last_text
        self._restart_flush()
        if getattr(results, "speech_final", False) and text:
            self._segments.append(text)
            self._confidence = confidence

    def _restart_flush(self) -> None:
        self._cancel_flush()
        self._flush_task = asyncio.create_task(self._flush_after_turn())

    def _cancel_flush(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None

    async def _flush_after_turn(self) -> None:
        await asyncio.sleep(settings.VOICE_STT_END_OF_TURN_MS / 1000)
        # Ya no es cancelable: evitar que un `SpeechStarted` que llegue mientras
        # se emite el turno cancele la callback y pierda lo que dijo el cliente.
        self._flush_task = None
        await self._emit_turn(source="silence")

    async def _emit_turn(self, *, source: str) -> None:
        self._cancel_flush()
        text = " ".join(self._segments).strip() or self._last_text.strip()
        confidence = self._confidence
        self._segments = []
        self._last_text = ""
        self._confidence = 0.0
        if not text:
            return
        logger.info("Turno final (%s, conf=%.2f): %s", source, confidence, text)
        await self._on_transcript(text, confidence)
