"""Servicio de Text-to-Speech en streaming con ElevenLabs.

Twilio solo reproduce μ-law 8 kHz en un Media Stream, así que se pide
`output_format=ulaw_8000` a ElevenLabs y el audio se reenvía tal cual: ni
resampleo ni transcodificación en el backend, que es lo que añade latencia.
"""

import logging
import time
from collections.abc import AsyncGenerator

import httpx

from app.core.settings import settings

logger = logging.getLogger(__name__)

#: Formato nativo de los Media Streams de Twilio.
_OUTPUT_FORMAT = "ulaw_8000"


class ElevenLabsTTSService:
    def __init__(self):
        self.api_key = settings.ELEVENLABS_API_KEY
        if not self.api_key:
            logger.warning("ELEVENLABS_API_KEY no está configurado")
        self.base_url = "https://api.elevenlabs.io/v1"
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Accept": "application/octet-stream", "xi-api-key": self.api_key or ""},
        )

    async def text_to_speech_stream(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """Genera μ-law 8 kHz en streaming, rindiendo el primer chunk cuanto antes.

        Los errores de ElevenLabs se propagan: es el canal de voz quien decide si
        recurrir a `<Say>` de Twilio o disculparse con el cliente.
        """
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY no está configurado en `.env`.")

        url = f"{self.base_url}/text-to-speech/{voice_id or settings.VOICE_TTS_VOICE_ID}/stream"
        started = time.perf_counter()
        first_chunk = True

        async with self.client.stream(
            "POST",
            url,
            params={"output_format": _OUTPUT_FORMAT},
            json={
                "text": text,
                "model_id": model_id or settings.VOICE_TTS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.5},
            },
        ) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"ElevenLabs {response.status_code}: {detail[:300]}")
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                if first_chunk:
                    first_chunk = False
                    logger.info(
                        "Primer byte de TTS en %.0f ms", (time.perf_counter() - started) * 1000
                    )
                yield chunk


elevenlabs_tts_service = ElevenLabsTTSService()
