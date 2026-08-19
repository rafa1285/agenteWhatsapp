"""Agregador de tools: el punto que suma las tools de todos los modulos.

Segun CLAUDE.md, `app/agent/` contiene solo el orquestador y este punto de
agregacion; cada modulo expone sus propias tools en su `tools.py`. El orquestador
(Fase 4) usara `tool_schemas()` para pasarlas al LLM y `tool_by_name()` para
despachar los `tool_use`.
"""

from typing import Any

from app.agent.models import EscalationReason
from app.agent.schemas import EscalateInput
from app.agent.service import create_escalation
from app.agent.tool import Tool, ToolContext
from app.modules.availability.tools import check_availability_tool
from app.modules.faqs.tools import answer_faq_tool
from app.modules.reservations.tools import (
    cancel_booking_tool,
    create_booking_tool,
    modify_booking_tool,
)

#: Mensaje que devuelve la tool `escalate` para que el agente transmita la
#: derivación al cliente.
HUMAN_HANDOFF_MESSAGE = (
    "Entiendo. Te pongo con el equipo del restaurante para que puedan atenderte; "
    "ya tienen el contexto de nuestra conversación."
)


async def escalate_tool_fn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Deriva la conversación a un humano (queja, clarificación fallida o fallo)."""
    if ctx.conversation_id is None:
        return {
            "ok": False,
            "error": "sin_conversacion",
            "message": "No hay una conversación activa que escalar.",
        }
    payload = EscalateInput.model_validate(args)
    escalation = await create_escalation(
        ctx.session,
        restaurant_id=ctx.restaurant_id,
        conversation_id=ctx.conversation_id,
        reason=EscalationReason(payload.reason),
    )
    return {
        "ok": True,
        "escalation": {"id": str(escalation.id), "reason": escalation.reason.value},
        "message": HUMAN_HANDOFF_MESSAGE,
    }


escalate_tool = Tool(
    name="escalate",
    description=(
        "Deriva la conversación a un humano: cuando el cliente muestra una queja o "
        "tono negativo, tras varios intentos de clarificación fallidos, o ante un "
        "fallo que no puedes resolver. El equipo recibe el contexto completo."
    ),
    input_schema=EscalateInput.model_json_schema(),
    func=escalate_tool_fn,
)

AGENT_TOOLS: tuple[Tool, ...] = (
    check_availability_tool,
    create_booking_tool,
    modify_booking_tool,
    cancel_booking_tool,
    answer_faq_tool,
    escalate_tool,
)


def tool_schemas() -> list[dict[str, Any]]:
    """Schemas de las tools en formato Anthropic (name, description, input_schema)."""
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in AGENT_TOOLS
    ]


def tool_by_name(name: str) -> Tool | None:
    """Lookup de una tool por nombre (para despachar `tool_use`)."""
    return next((tool for tool in AGENT_TOOLS if tool.name == name), None)
