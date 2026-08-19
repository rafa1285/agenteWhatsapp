"""Servicio de FAQs (RAG ligero sobre datos del restaurante).

Sin tabla `faqs` (CLAUDE.md: "sin modelo propio"): se responde con datos reales
de `Restaurant` para las categorias que cubre (horario, telefono, idiomas,
grupos). Cualquier otra cosa devuelve `known=False` para derivar a un humano;
nunca inventa datos. El contrato `FaqAnswer` es la costura donde la Fase 4
enchufa el RAG real sin cambiar la firma de `answer_faq`.
"""

import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Restaurant

HORARIO_KEYWORDS = ("hora", "abre", "cierra", "horario", "abierto", "mediodia", "comida", "cena")
TELEFONO_KEYWORDS = ("telefono", "llamar", "llamada", "contacto", "llamarnos")
IDIOMAS_KEYWORDS = ("idioma", "idiomas", "ingles", "frances", "hablan", "habla")
GRUPOS_KEYWORDS = ("grupo", "grupos", "cumpleanos", "evento", "celebracion")

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


def _normalize(question: str) -> str:
    """Normaliza para clasificar: minusculas y sin acentos ("teléfono" -> "telefono")."""
    nfd = unicodedata.normalize("NFD", question)
    return "".join(c for c in nfd if not unicodedata.combining(c)).lower()


def _classify(question: str) -> str | None:
    """Clasifica la intencion por keywords (orden: horario, telefono, idiomas, grupos)."""
    q = _normalize(question)
    for keywords, category in (
        (HORARIO_KEYWORDS, "horario"),
        (TELEFONO_KEYWORDS, "telefono"),
        (IDIOMAS_KEYWORDS, "idiomas"),
        (GRUPOS_KEYWORDS, "grupos"),
    ):
        if any(k in q for k in keywords):
            return category
    return None


async def answer_faq(
    session: AsyncSession, *, restaurant_id: uuid.UUID, question: str
) -> FaqAnswer:
    """Responde una pregunta frecuente con datos reales del restaurante."""
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        return _unknown()

    category = _classify(question)
    if category == "horario":
        if restaurant.opening_time is None or restaurant.closing_time is None:
            return _unknown()
        return FaqAnswer(
            answer=(
                f"{restaurant.name} abre a las {restaurant.opening_time:%H:%M} "
                f"y cierra a las {restaurant.closing_time:%H:%M}."
            ),
            known=True,
            category="horario",
        )
    if category == "telefono":
        return FaqAnswer(
            answer=f"Puedes llamar al {restaurant.public_phone}.",
            known=True,
            category="telefono",
        )
    if category == "idiomas":
        languages = ", ".join(restaurant.supported_languages)
        return FaqAnswer(
            answer=f"Atendemos en los siguientes idiomas: {languages}.",
            known=True,
            category="idiomas",
        )
    if category == "grupos":
        threshold = restaurant.large_group_threshold
        return FaqAnswer(
            answer=(
                f"Para grupos de más de {threshold} comensales te pongo en contacto "
                "con el equipo del restaurante."
            ),
            known=True,
            category="grupos",
        )
    return _unknown()
