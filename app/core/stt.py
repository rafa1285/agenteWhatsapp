"""Servicio de Speech-to-Text usando Deepgram en tiempo real."""

import logging

from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

from app.core.settings import settings

logger = logging.getLogger(__name__)


class DeepgramSTTService:
    def __init__(self):
        if not settings.DEEPGRAM_API_KEY:
            raise ValueError("DEEPGRAM_API_KEY no está configurado en settings")
        self.client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        self.connection = None

    async def connect(self, on_message_callback, on_error_callback=None, on_close_callback=None):
        """Establece la conexión WebSocket con Deepgram para transcripción en tiempo real."""
        try:
            self.connection = self.client.listen.live.v("1")

            # Configurar opciones de transcripción
            options = LiveOptions(
                model="nova-2",
                language="es",
                smart_format=True,
                encoding="linear16",
                sample_rate=16000,
                interim_results=True,
                utterance_end_ms="800",  # Reducido de 1000ms para mayor agilidad en el turno
                vad_events=True,  # Detectar actividad de voz para barge-in
            )

            # Añadir manejadores de eventos
            self.connection.on(LiveTranscriptionEvents.Transcript, on_message_callback)
            if on_error_callback:
                self.connection.on(LiveTranscriptionEvents.Error, on_error_callback)
            if on_close_callback:
                self.connection.on(LiveTranscriptionEvents.Close, on_close_callback)

            # Iniciar la conexión
            self.connection.start(options)
            logger.info("Conexión con Deepgram establecida")
            return True
        except Exception as e:
            logger.error("Error al conectar con Deepgram: %s", e, exc_info=True)
            return False

    async def send_audio(self, audio_data: bytes):
        """Envía datos de audio PCM a Deepgram para transcripción."""
        if self.connection and self.connection.is_active():
            try:
                self.connection.send(audio_data)
            except Exception as e:
                logger.error("Error enviando audio a Deepgram: %s", e, exc_info=True)

    async def finish(self):
        """Finaliza la transcripción y cierra la conexión."""
        if self.connection:
            try:
                self.connection.finish()
                logger.info("Conexión con Deepgram finalizada")
            except Exception as e:
                logger.error("Error finalizando conexión con Deepgram: %s", e, exc_info=True)
            finally:
                self.connection = None


deepgram_stt_service = DeepgramSTTService()
