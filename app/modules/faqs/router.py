"""Router REST de FAQs (consulta keyword-based sobre datos del restaurante)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.models import Restaurant
from app.modules.faqs.service import FaqAnswer, answer_faq

router = APIRouter(prefix="/api/v1/faqs", tags=["faqs"], dependencies=[Depends(get_current_restaurant)])


@router.get("/ask", response_model=FaqAnswer)
async def ask_faq(
    question: Annotated[str, Query(min_length=3, max_length=500)],
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FaqAnswer:
    """
    Consultar FAQ con pregunta en lenguaje natural.

    Devuelve `FaqAnswer` con `known=True` si la categoría está soportada
    (horario, teléfono, idiomas, grupos); `known=False` en caso contrario
    para que el cliente derive a humano.
    """
    return await answer_faq(session=session, restaurant_id=restaurant.id, question=question)


@router.get("/categories")
async def list_faq_categories() -> dict[str, list[str]]:
    """Listar categorías soportadas y ejemplos de preguntas."""
    return {
        "horario": ["¿A qué hora abren?", "¿Hasta qué hora está abierto?", "Horario de comidas"],
        "telefono": ["¿Cuál es el teléfono?", "¿Cómo les llamo?", "Teléfono de contacto"],
        "idiomas": ["¿Hablan inglés?", "¿En qué idiomas atienden?"],
        "grupos": ["¿Aceptan grupos grandes?", "¿Hasta cuántos para un cumpleaños?"],
    }
