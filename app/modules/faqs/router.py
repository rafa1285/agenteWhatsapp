"""Router REST de FAQs (gestión y consulta de Knowledge Base en Qdrant)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.embeddings import embedding_service
from app.core.models import Restaurant
from app.core.vector_store import vector_store_service
from app.modules.faqs.service import FaqAnswer, answer_faq

router = APIRouter(
    prefix="/api/v1/faqs", tags=["faqs"], dependencies=[Depends(get_current_restaurant)]
)


class FaqEntry(BaseModel):
    """Esquema para cargar una pregunta y respuesta en la KB."""

    question: str
    answer: str


@router.get("/ask", response_model=FaqAnswer)
async def ask_faq(
    question: Annotated[str, Query(min_length=3, max_length=500)],
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FaqAnswer:
    """
    Consultar FAQ usando búsqueda semántica en Qdrant.
    """
    return await answer_faq(session=session, restaurant_id=restaurant.id, question=question)


@router.post("/index")
async def index_faq(
    entry: FaqEntry,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
) -> dict:
    """
    Indexar una nueva pregunta/respuesta en la base de conocimientos del restaurante.
    Cálculo del embedding y guardado en Qdrant.
    """
    try:
        vector = await embedding_service.get_embedding(entry.question)
        await vector_store_service.upsert_faq(
            restaurant_id=str(restaurant.id),
            question=entry.question,
            answer=entry.answer,
            vector=vector,
        )
        return {"status": "indexed", "question": entry.question}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error indexando FAQ: {e!s}")


@router.delete("/clear")
async def clear_faqs(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
) -> dict:
    """
    Borrar toda la base de conocimientos de este restaurante.
    """
    try:
        await vector_store_service.delete_restaurant_faqs(restaurant_id=str(restaurant.id))
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error borrando FAQs: {e!s}")
