"""Servicio de conversaciones y escalaciones (persistencia del orquestador).

`Conversation` y `Escalation` son metadatos de la interacción con el LLM, no
dominio del restaurante; por eso su servicio vive en `app/agent/`. Las funciones
hacen `flush` (nunca `commit`): el límite de la transacción lo decide el caller
(webhook de WhatsApp / canal de voz / panel).
"""

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import (
    Conversation,
    ConversationChannel,
    ConversationOutcome,
    Escalation,
    EscalationReason,
)


def transcript_to_json(turns: list[dict]) -> str:
    """Serializa los turnos de texto de una conversación como JSON."""
    return json.dumps(turns, ensure_ascii=False)


def transcript_from_json(raw: str | None) -> list[dict]:
    """Deserializa el transcript persistido; None/vacío/inválido -> lista vacía."""
    if not raw:
        return []
    try:
        turns = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return turns if isinstance(turns, list) else []


async def create_conversation(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    channel: ConversationChannel,
    transcript: str = "",
) -> Conversation:
    """Crea la fila de conversación (al inicio de `run_conversation`).

    Se crea antes de ejecutar el bucle para que la tool `escalate` tenga el
    `conversation_id`; el transcript y el outcome se fijan al finalizar.
    """
    conversation = Conversation(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        channel=channel,
        transcript=transcript,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def finalize_conversation(
    session: AsyncSession,
    *,
    conversation: Conversation,
    transcript: str,
    outcome: ConversationOutcome,
) -> None:
    """Fija el transcript final y el outcome de la conversación."""
    conversation.transcript = transcript
    conversation.outcome = outcome
    await session.flush()


async def create_escalation(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    reason: EscalationReason,
) -> Escalation:
    """Crea una escalación a humano asociada a la conversación."""
    escalation = Escalation(
        restaurant_id=restaurant_id,
        conversation_id=conversation_id,
        reason=reason,
    )
    session.add(escalation)
    await session.flush()
    # Notificar al panel en tiempo real (no bloquea la transacción).
    from app.core.webhook import emit_escalation_event

    await emit_escalation_event("escalation.created", escalation)
    return escalation


async def latest_conversation_transcript(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: ConversationChannel,
    since: datetime | None = None,
) -> str | None:
    """Devuelve el transcript (JSON) de la conversación más reciente del canal.

    Lo usa el webhook para construir el `prior_transcript` que reenvía al LLM al
    retomar una conversación (§12). Filtra por tenant y canal; un transcript
    vacío o la ausencia de conversaciones devuelven `None`. Con `since`, solo se
    consideran conversaciones posteriores a esa fecha (el canal de voz pasa el
    inicio de la llamada para no retomar contexto de llamadas anteriores).
    """
    stmt = select(Conversation.transcript).where(
        Conversation.restaurant_id == restaurant_id,
        Conversation.customer_id == customer_id,
        Conversation.channel == channel,
    )
    if since is not None:
        stmt = stmt.where(Conversation.date >= since)
    stmt = stmt.order_by(Conversation.date.desc()).limit(1)
    transcript = await session.scalar(stmt)
    return transcript or None
