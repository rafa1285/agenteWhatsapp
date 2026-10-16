"""Servicio de embeddings para convertir texto en vectores.
Usa OpenAI por defecto según settings.EMBEDDING_MODEL.
"""

import logging

from openai import AsyncOpenAI

from app.core.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.EMBEDDING_MODEL

    async def get_embedding(self, text: str) -> list[float]:
        """Convierte un texto en un vector de embeddings."""
        try:
            response = await self.client.embeddings.create(input=[text.strip()], model=self.model)
            return response.data[0].embedding
        except Exception as e:
            logger.error("Error obteniendo embedding: %s", e, exc_info=True)
            raise


embedding_service = EmbeddingService()
