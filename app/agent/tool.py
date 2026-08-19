"""Contrato de tools del agente LLM.

`Tool`/`ToolContext` viven aquí (y no en `app/agent/tools.py`) para evitar el
ciclo de imports: el agregador `app/agent/tools.py` importa los `tools.py` de
los módulos, y estos importan `Tool` desde aquí. `tool.py` solo depende de
`reservations.models`, que no importa nada de `app.agent`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reservations.models import SourceChannel


@dataclass(frozen=True)
class ToolContext:
    """Contexto por conversación inyectado por el orquestador (Fase 4).

    Los identificadores (restaurant/customer/reservation) y el canal NO forman
    parte de los args que emite el LLM: llegan aquí, resueltos por el orquestador.
    """

    session: AsyncSession
    restaurant_id: uuid.UUID
    source_channel: SourceChannel
    customer_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Tool:
    """Una tool expuesta al LLM para tool-calling.

    `input_schema` es el JSON Schema (formato Anthropic) derivado de un Pydantic
    público. `func` recibe el contexto de la conversación y los args ya validados
    por el orquestador, y devuelve un dict JSON-serializable. Nunca lanza hacia
    el LLM: los errores de negocio se devuelven como dicts con `ok: False`.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]
