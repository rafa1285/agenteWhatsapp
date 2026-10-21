"""Servicio de persistencia vectorial usando Qdrant.
Maneja la indexación y búsqueda de FAQs multi-tenant.
"""

import logging
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.settings import settings

logger = logging.getLogger(__name__)


class VectorStoreService:
    def __init__(self):
        self.collection_name = "restaurant_faqs"
        self._client: AsyncQdrantClient | None = None

    @property
    def client(self) -> AsyncQdrantClient:
        # Perezoso: en modo embebido abrir el cliente bloquea `QDRANT_PATH`, así
        # que no debe crearse al importar la app (tests y otros procesos no usan
        # la base de conocimientos).
        if self._client is None:
            if settings.QDRANT_PATH:
                # Modo embebido (desarrollo): ficheros locales, sin Docker, y un
                # único proceso a la vez.
                self._client = AsyncQdrantClient(path=settings.QDRANT_PATH)
            else:
                self._client = AsyncQdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY or None,
                )
        return self._client

    async def ensure_collection(self):
        """Crea la colección de FAQs si no existe."""
        try:
            collections = await self.client.get_collections()
            if self.collection_name not in [c.name for c in collections.collections]:
                logger.info("Creando colección de vectores: %s", self.collection_name)
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=settings.EMBEDDING_DIM, distance=Distance.COSINE
                    ),
                )
        except Exception as e:
            logger.error("Error asegurando colección de Qdrant: %s", e, exc_info=True)
            raise

    async def upsert_faq(self, restaurant_id: str, question: str, answer: str, vector: list[float]):
        """Inserta o actualiza una FAQ en la base de datos vectorial."""
        # Qdrant solo acepta UUID o enteros como id; UUIDv5 es determinista, asi que
        # reindexar la misma pregunta del mismo restaurante actualiza el punto en vez
        # de duplicarlo.
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{restaurant_id}:{question}"))

        await self.ensure_collection()
        await self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "restaurant_id": restaurant_id,
                        "question": question,
                        "answer": answer,
                    },
                )
            ],
        )

    async def search_faqs(
        self, restaurant_id: str, query_vector: list[float], limit: int = 3
    ) -> list[dict]:
        """Busca las FAQs más relevantes para un restaurante específico."""
        search_result = await self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="restaurant_id",
                        match=MatchValue(value=restaurant_id),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
        )

        return [
            {
                "question": hit.payload["question"],
                "answer": hit.payload["answer"],
                "score": hit.score,
            }
            for hit in search_result.points
        ]

    async def delete_restaurant_faqs(self, restaurant_id: str):
        """Elimina todas las FAQs de un restaurante (ej. derecho al olvido)."""
        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="restaurant_id",
                        match=MatchValue(value=restaurant_id),
                    )
                ]
            ),
        )


vector_store_service = VectorStoreService()
