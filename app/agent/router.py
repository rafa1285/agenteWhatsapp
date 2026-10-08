"""Router para logs de conversaciones del agente (panel → backend)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Conversation, ConversationChannel, ConversationOutcome
from app.core.dependencies import get_current_restaurant, get_db_session
from app.core.models import Restaurant

router = APIRouter(
    prefix="/api/v1/agent/conversations",
    tags=["agent-conversations"],
    dependencies=[Depends(get_current_restaurant)],
)


@router.get("", response_model=list[dict])
async def list_conversations(
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    channel: Annotated[ConversationChannel | None, Query()] = None,
    outcome: Annotated[ConversationOutcome | None, Query()] = None,
    since: Annotated[str | None, Query()] = None,
):
    """Listar conversaciones del restaurante actual con filtros opcionales."""
    stmt = select(Conversation).where(Conversation.restaurant_id == restaurant.id)

    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if outcome:
        stmt = stmt.where(Conversation.outcome == outcome)
    if since:
        from datetime import datetime

        try:
            since_dt = datetime.fromisoformat(since)
            stmt = stmt.where(Conversation.date >= since_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato de fecha inválido. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS)",
            )

    stmt = stmt.order_by(desc(Conversation.date)).limit(limit).offset(offset)

    result = await session.execute(stmt)
    conversations = result.scalars().all()

    # Convertir a diccionarios para la respuesta JSON
    return [
        {
            "id": str(conv.id),
            "restaurant_id": str(conv.restaurant_id),
            "customer_id": str(conv.customer_id) if conv.customer_id else None,
            "channel": conv.channel,
            "transcript": conv.transcript,
            "outcome": conv.outcome,
            "date": conv.date.isoformat() if conv.date else None,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        }
        for conv in conversations
    ]


@router.get("/{conversation_id}", response_model=dict)
async def get_conversation(
    conversation_id: str,
    restaurant: Annotated[Restaurant, Depends(get_current_restaurant)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Obtener una conversación específica por ID (verifica tenant)."""
    from uuid import UUID

    try:
        conv_id = UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="UUID inválido")

    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.restaurant_id == restaurant.id,
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversación no encontrada",
        )

    return {
        "id": str(conversation.id),
        "restaurant_id": str(conversation.restaurant_id),
        "customer_id": str(conversation.customer_id) if conversation.customer_id else None,
        "channel": conversation.channel,
        "transcript": conversation.transcript,
        "outcome": conversation.outcome,
        "date": conversation.date.isoformat() if conversation.date else None,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }
