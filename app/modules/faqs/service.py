"""Servicio de FAQs (RAG sobre base de conocimientos en Qdrant).
Sustituye la clasificación por keywords por búsqueda semántica vectorial.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import embedding_service
from app.core.models import Restaurant
from app.core.settings import settings
from app.core.vector_store import vector_store_service

logger = logging.getLogger(__name__)

UNKNOWN_ANSWER = (
    "No tengo esa información con certeza; te pongo en contacto con el equipo del restaurante."
)


@dataclass(frozen=True)
class FaqAnswer:
    """Respuesta de FAQ. `known=False` indica que no se sabe y hay que derivar."""

    answer: str
    known: bool
    category: str


def _unknown() -> FaqAnswer:
    return FaqAnswer(answer=UNKNOWN_ANSWER, known=False, category="unknown")


async def answer_faq(
    session: AsyncSession, *, restaurant_id: uuid.UUID, question: str
) -> FaqAnswer:
    """Responde una pregunta frecuente usando búsqueda semántica en Qdrant."""
    # 1. Verificar que el restaurante existe
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        return _unknown()

    try:
        # 2. Convertir la pregunta del usuario en un vector
        query_vector = await embedding_service.get_embedding(question)

        # 3. Buscar las FAQs más relevantes para este tenant en Qdrant
        results = await vector_store_service.search_faqs(
            restaurant_id=str(restaurant_id), query_vector=query_vector, limit=1
        )

        if not results:
            # Fallback: Si no hay nada en Qdrant, podríamos intentar la lógica antigua
            # o simplemente devolver unknown. Para mantener coherencia con el nuevo
            # sistema, devolvemos unknown si no hay matches semánticos.
            return _unknown()

        # 4. Retornar la respuesta más relevante si supera el umbral de similitud
        best_match = results[0]
        if best_match["score"] < settings.FAQ_RAG_SCORE_THRESHOLD:
            return _unknown()

        return FaqAnswer(
            answer=best_match["answer"],
            known=True,
            category="rag_knowledge_base",
        )

    except Exception as e:
        # En caso de error técnico con Qdrant o el modelo de embeddings, no
        # bloqueamos la conversación: derivamos a humano.
        logger.error("Error en RAG de FAQs: %s", e, exc_info=True)
        return _unknown()
