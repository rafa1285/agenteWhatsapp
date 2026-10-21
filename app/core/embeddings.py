"""Servicio de embeddings con FastEmbed (modelos ONNX multilingues locales).

No depende de ninguna API de pago: el modelo se descarga la primera vez a
`settings.EMBEDDING_CACHE_DIR` y corre en CPU. Claude/Anthropic no expone un
endpoint de embeddings, asi que el LLM del agente y la vectorizacion son
independientes por diseno.
"""

import asyncio
import logging

from app.core.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL
        self._model = None

    def _load(self):
        if self._model is None:
            # Import diferido: arrastra onnxruntime, ~100 MB que no deben pesar
            # al importar la app cuando no se usa la base de conocimientos.
            from fastembed import TextEmbedding

            logger.info("Cargando modelo de embeddings: %s", self.model_name)
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=settings.EMBEDDING_CACHE_DIR,
            )
        return self._model

    async def get_embedding(self, text: str) -> list[float]:
        """Convierte un texto en un vector de embeddings."""
        vectors = await asyncio.to_thread(list, self._load().embed(text.strip()))
        return vectors[0].tolist()


embedding_service = EmbeddingService()
