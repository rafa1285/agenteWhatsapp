"""Schemas de FAQs (contrato público del módulo)."""

from pydantic import BaseModel, Field


class FaqQueryInput(BaseModel):
    """Pregunta que el LLM emite para `answer_faq`."""

    question: str = Field(min_length=1)
