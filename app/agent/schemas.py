"""Schemas públicos LLM del módulo agente (orquestador)."""

from typing import Literal

from pydantic import BaseModel, Field

#: Motivos de escalación que decide el propio LLM. Los otros motivos de
#: `EscalationReason` (`large_group`, `voice_transfer_failed`) los detecta el
#: sistema, no el modelo.
EscalationReasonChoice = Literal["complaint", "clarification_failed", "technical_failure"]


class EscalateInput(BaseModel):
    """Args de la tool `escalate`: deriva la conversación a un humano.

    `summary` no se persiste (el modelo `Escalation` no tiene columna propia);
    el contexto completo viaja en el transcript de la conversación.
    """

    reason: EscalationReasonChoice
    summary: str = Field(min_length=1)
