"""Manejador de flujo de medios en tiempo real para voz.

Coordina:
1. Recibir audio PCM de Twilio vía WebSocket
2. Enviar audio a Deepgram para transcripción en tiempo real
3. Recibir transcripciones parciales y finales de Deepgram
4. Procesar transcripciones finales con el orquestador LLM
5. Convertir respuestas LLM a audio con ElevenLabs (streaming)
6. Enviar audio de vuelta a Twilio vía WebSocket
7. Manejar barge-in: detener TTS cuando se detecta habla del usuario
"""

import base64
import json
import logging

from app.agent.models import ConversationOutcome, SourceChannel
from app.core.models import Restaurant
from app.core.stt import deepgram_stt_service
from app.core.tts import elevenlabs_tts_service

logger = logging.getLogger(__name__)


class VoiceStreamHandler:
    def __init__(
        self,
        websocket,
        session_factory,
        llm_client,
        whatsapp_gateway,
        restaurant: Restaurant,
        customer_id: str | None = None,
    ):
        self.websocket = websocket
        self.session_factory = session_factory
        self.llm_client = llm_client
        self.whatsapp_gateway = whatsapp_gateway
        self.restaurant = restaurant
        self.customer_id = customer_id

        # Estado de la conversación
        self.is_speaking = False  # ¿Está el agente hablando actualmente?
        self.is_processing = False  # ¿Estamos procesando una transcripción?
        self.latest_transcript = ""  # Última transcripción parcial
        self.final_transcript = ""  # Transcripción final acumulada
        self.conversation_transcript = ""  # Transcripción completa de la conversación
        self.stream_sid = None  # ID del flujo de Twilio necesario para enviar audio y marcas

        # Tareas asíncronas
        self.deepgram_task = None
        self.tts_task = None

    async def handle(self):
        """Punto de entrada principal para manejar el flujo de medios."""
        try:
            # Conectar con Deepgram
            await deepgram_stt_service.connect(
                on_message_callback=self._handle_deepgram_transcript,
                on_error_callback=self._handle_deepgram_error,
                on_close_callback=self._handle_deepgram_close,
            )

            # Enviar saludo inicial
            await self._send_initial_greeting()

            # Bucle principal de mensajes
            await self._message_loop()

        except Exception as e:
            logger.error("Error en VoiceStreamHandler: %s", e, exc_info=True)
        finally:
            await self._cleanup()

    async def _send_initial_greeting(self):
        """Envía el saludo inicial al usuario."""
        greeting = f"Bienvenido a {self.restaurant.name}. Esta llamada puede ser grabada con fines de calidad y formación. Cuéntame, ¿en qué puedo ayudarte?"
        await self._speak(greeting)

    async def _message_loop(self):
        """Bucle principal para recibir mensajes de Twilio."""
        while True:
            try:
                message = await self.websocket.receive_text()
                data = json.loads(message)

                event_type = data.get("event")

                if event_type == "media":
                    # Recibir audio de Twilio (payload base64)
                    payload = data.get("media", {}).get("payload")
                    if payload:
                        audio_data = base64.b64decode(payload)
                        # Enviar audio a Deepgram para transcripción
                        await deepgram_stt_service.send_audio(audio_data)

                elif event_type == "start":
                    start_data = data.get("start", {})
                    self.stream_sid = start_data.get("streamSid")
                    logger.info("Stream de medios iniciado: %s", self.stream_sid)

                elif event_type == "stop":
                    logger.info("Stream de medios detenido")
                    break

                elif event_type == "mark":
                    # Marcas para sincronización (útil para barge-in)
                    mark_name = data.get("mark", {}).get("name")
                    if mark_name == "speech_start":
                        # El usuario comenzó a hablar (posible barge-in)
                        await self._handle_barge_in()

            except Exception as e:
                logger.error("Error procesando mensaje de WebSocket: %s", e, exc_info=True)
                break

    async def _handle_deepgram_transcript(self, *args, **kwargs):
        """Maneja los resultados de transcripción de Deepgram."""
        try:
            # El formato exacto depende de la versión del SDK de Deepgram
            # Asumiendo que el primer argumento es el resultado
            if args:
                result = args[0]
            else:
                result = kwargs.get("transcript", {})

            transcript = result.get("transcript", "")
            is_final = result.get("is_final", False)
            confidence = result.get("confidence", 0.0)

            if is_final and transcript.strip():
                # Transcripción final: procesar con el LLM
                await self._process_final_transcript(transcript)
            elif transcript and not self.is_speaking:
                # Transcripción parcial mientras no estamos hablando: actualizar para mostrar actividad
                self.latest_transcript = transcript

        except Exception as e:
            logger.error("Error manejando transcripción de Deepgram: %s", e, exc_info=True)

    async def _handle_deepgram_error(self, error):
        """Maneja errores de Deepgram."""
        logger.error("Error de Deepgram: %s", error)

    async def _handle_deepgram_close(self):
        """Maneja el cierre de la conexión con Deepgram."""
        logger.info("Conexión con Deepgram cerrada")

    async def _process_final_transcript(self, transcript: str):
        """Procesa una transcripción final del usuario usando streaming para reducir latencia."""
        if self.is_processing:
            # Ya estamos procesando, ignorar para evitar duplicados
            return

        self.is_processing = True
        self.final_transcript += " " + transcript if self.final_transcript else transcript
        logger.info("Transcripción final recibida: %s", transcript)

        try:
            # Obtener sesión de base de datos
            async for session in self.session_factory():
                # Procesar con el orquestador LLM en modo streaming
                sentence_buffer = ""
                final_result = None

                async for token, result in run_conversation_stream(
                    session,
                    llm=self.llm_client,
                    restaurant=self.restaurant,
                    source_channel=SourceChannel.VOICE,
                    incoming_message=transcript,
                    customer_id=self.customer_id,
                    prior_transcript=self.conversation_transcript,
                ):
                    if token:
                        sentence_buffer += token
                        # Optimización First Byte: Enviamos a TTS en cuanto detectamos fin de frase
                        if any(punct in token for punct in (".", "!", "?", "\n")):
                            await self._speak(sentence_buffer.strip())
                            sentence_buffer = ""

                    if result:
                        final_result = result

                # Enviar cualquier remanente del buffer
                if sentence_buffer.strip():
                    await self._speak(sentence_buffer.strip())

                if not final_result:
                    logger.error("run_conversation_stream no devolvió un ConversationResult")
                    return

                # Actualizar transcripción de conversación
                self.conversation_transcript += (
                    f"Usuario: {transcript}\nAgente: {final_result.text}\n"
                )

                # Manejar confirmación de reserva por WhatsApp
                if final_result.outcome == ConversationOutcome.RESERVATION_CREATED:
                    if self.customer_id:
                        try:
                            from sqlalchemy import select

                            from app.core.models import Customer

                            stmt = select(Customer.phone).where(Customer.id == self.customer_id)
                            res = await session.execute(stmt)
                            phone = res.scalar_one_or_none()
                            if phone:
                                await self.whatsapp_gateway.send_text(
                                    to=phone, text=final_result.text
                                )
                                logger.info(
                                    "Confirmación de reserva enviada por WhatsApp a %s", phone
                                )
                        except Exception as e:
                            logger.error(
                                "Error enviando confirmación WhatsApp: %s", e, exc_info=True
                            )

                break  # Salir del bucle de sesión

        except Exception as e:
            logger.error("Error procesando transcripción final: %s", e, exc_info=True)
            await self._speak("Lo siento, tuve un problema técnico. ¿Podrías repetirlo?")
        finally:
            self.is_processing = False

    async def _speak(self, text: str):
        """Convierte texto a audio usando ElevenLabs y lo envía a Twilio."""
        if self.is_speaking:
            # Ya estamos hablando, esperar o manejar según política
            return

        self.is_speaking = True
        logger.info("Iniciando síntesis de voz: %s", text[:50])

        try:
            # Marcar el inicio de la habla para barge-in detection
            await self._send_mark("speech_start")

            # Streaming de audio desde ElevenLabs
            async for chunk in elevenlabs_tts_service.text_to_speech_stream(text):
                # Enviar chunk a Twilio inmediatamente para reducir latencia
                await self._send_audio(chunk)

        except Exception as e:
            logger.error("Error en síntesis de voz: %s", e, exc_info=True)
            # Fallback: enviar mensaje de error como texto
            await self._send_audio_fallback("Lo siento, tuve un problema técnico.")
        finally:
            self.is_speaking = False
            # Marcar el fin de la habla
            await self._send_mark("speech_end")

    async def _send_audio(self, audio_data: bytes):
        """Envía datos de audio PCM a Twilio."""
        payload = base64.b64encode(audio_data).decode("utf-8")
        message = {"event": "media", "media": {"payload": payload}}
        await self.websocket.send_text(json.dumps(message))

    async def _send_mark(self, name: str):
        """Envía una marca a Twilio para sincronización."""
        if not self.stream_sid:
            logger.warning("Intento de enviar marca sin stream_sid")
            return
        message = {
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {"name": name},
        }
        await self.websocket.send_text(json.dumps(message))

    async def _handle_barge_in(self):
        """Maneja el barge-in: el usuario interrumpió mientras el agente hablaba."""
        if self.is_speaking:
            logger.info("Barge-in detectado: deteniendo TTS")
            self.is_speaking = False
            # Enviar señal 'clear' a Twilio para vaciar el buffer de audio
            if self.stream_sid:
                message = {
                    "event": "clear",
                    "streamSid": self.stream_sid,
                }
                await self.websocket.send_text(json.dumps(message))

    async def _send_audio_fallback(self, text: str):
        """Envía un mensaje de audio de fallback (más simple)."""
        # Para evitar complejidad, podríamos enviar un mensaje pre-grabado
        # o simplemente terminar la llamada gracefully
        logger.warning("Usando fallback de audio: %s", text)
        # Implementación simplificada: enviar texto como mensaje
        pass

    async def _cleanup(self):
        """Limpia recursos al terminar."""
        logger.info("Limpiando VoiceStreamHandler")
        if deepgram_stt_service.connection:
            await deepgram_stt_service.finish()
        # Cerrar otras conexiones si es necesario
