"""Servicio de Text-to-Speech usando ElevenLabs en streaming."""

import logging
from collections.abc import AsyncGenerator

import httpx

from app.core.settings import settings

logger = logging.getLogger(__name__)


class ElevenLabsTTSService:
    def __init__(self):
        self.api_key = settings.ELEVENLABS_API_KEY
        if not self.api_key:
            logger.warning("ELEVENLABS_API_KEY no está configurado")
        self.base_url = "https://api.elevenlabs.io/v1"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def text_to_speech_stream(
        self,
        text: str,
        voice_id: str = "EXAVITQu4vr4xnSDxMaL",  # Bella voice by default
        model_id: str = "eleven_multilingual_v2",
    ) -> AsyncGenerator[bytes, None]:
        """
        Convierte texto a audio en streaming usando ElevenLabs.
        Genera chunks de audio PCM que pueden enviarse directamente a Twilio.
        """
        if not self.api_key:
            logger.error("ElevenLabs API key no configurada")
            return

        url = f"{self.base_url}/text-to-speech/{voice_id}/stream"

        headers = {
            "Accept": "application/octet-stream",
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        data = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        try:
            async with self.client.stream("POST", url, json=data, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:  # Filter out keep-alive chunks
                        yield chunk
        except Exception as e:
            logger.error("Error en streaming de ElevenLabs TTS: %s", e, exc_info=True)


elevenlabs_tts_service = ElevenLabsTTSService()
