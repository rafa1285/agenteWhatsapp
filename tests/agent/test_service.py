"""Tests del servicio de conversaciones y escalaciones (BD real)."""

from datetime import UTC, datetime

from app.agent.models import (
    Conversation,
    ConversationChannel,
    ConversationOutcome,
    EscalationReason,
)
from app.agent.service import (
    create_conversation,
    create_escalation,
    finalize_conversation,
    latest_conversation_transcript,
    transcript_from_json,
    transcript_to_json,
)
from sqlalchemy import text


def test_transcript_round_trip() -> None:
    turns = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Buenas, ¿qué tal?"},
    ]
    raw = transcript_to_json(turns)
    assert isinstance(raw, str)
    assert transcript_from_json(raw) == turns


def test_transcript_from_json_invalid() -> None:
    assert transcript_from_json(None) == []
    assert transcript_from_json("") == []
    assert transcript_from_json("no-json") == []
    assert transcript_from_json('"solo un string"') == []


async def test_create_and_finalize_conversation(db_session, restaurant_factory, customer_factory):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)

    conversation = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
    )
    assert conversation.id is not None
    assert conversation.channel == ConversationChannel.WHATSAPP
    assert conversation.transcript == ""
    assert conversation.outcome is None

    await finalize_conversation(
        db_session,
        conversation=conversation,
        transcript='[{"role": "user", "content": "Hola"}]',
        outcome=ConversationOutcome.QUERY,
    )
    assert conversation.outcome == ConversationOutcome.QUERY
    assert conversation.transcript.startswith("[")

    stored = await db_session.get(Conversation, conversation.id)
    assert stored is not None
    assert stored.outcome == ConversationOutcome.QUERY


async def test_create_escalation_linked_to_conversation(
    db_session, restaurant_factory, customer_factory
):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)
    conversation = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
    )
    escalation = await create_escalation(
        db_session,
        restaurant_id=restaurant.id,
        conversation_id=conversation.id,
        reason=EscalationReason.COMPLAINT,
    )
    assert escalation.conversation_id == conversation.id
    assert escalation.reason == EscalationReason.COMPLAINT
    assert escalation.status.value == "pending"
    assert escalation.date is not None


async def test_create_escalation_falls_back_when_db_default_is_missing(
    db_session, restaurant_factory, customer_factory
):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)
    conversation = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
    )
    await db_session.execute(text("ALTER TABLE escalations ALTER COLUMN date DROP DEFAULT"))

    escalation = await create_escalation(
        db_session,
        restaurant_id=restaurant.id,
        conversation_id=conversation.id,
        reason=EscalationReason.COMPLAINT,
    )

    assert escalation.date is not None


async def test_latest_conversation_transcript_returns_most_recent(
    db_session, restaurant_factory, customer_factory
):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)
    older = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
        transcript='[{"role": "user", "content": "Hola"}]',
    )
    newer = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
        transcript='[{"role": "user", "content": "Quiero reservar"}]',
    )
    older.date = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    newer.date = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    await db_session.flush()

    transcript = await latest_conversation_transcript(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.WHATSAPP,
    )
    assert transcript == newer.transcript


async def test_latest_conversation_transcript_returns_none_without_any(
    db_session, restaurant_factory, customer_factory
):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)
    assert (
        await latest_conversation_transcript(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            channel=ConversationChannel.WHATSAPP,
        )
        is None
    )


async def test_latest_conversation_transcript_filters_tenant_and_channel(
    db_session, restaurant_factory, customer_factory
):
    restaurant_a = await restaurant_factory(name="Rest A")
    restaurant_b = await restaurant_factory(name="Rest B")
    customer_a = await customer_factory(restaurant_a.id)
    customer_b = await customer_factory(restaurant_b.id)
    await create_conversation(
        db_session,
        restaurant_id=restaurant_a.id,
        customer_id=customer_a.id,
        channel=ConversationChannel.WHATSAPP,
        transcript='[{"role": "user", "content": "Hola"}]',
    )
    await create_conversation(
        db_session,
        restaurant_id=restaurant_b.id,
        customer_id=customer_b.id,
        channel=ConversationChannel.WHATSAPP,
        transcript='[{"role": "user", "content": "Otra tenant"}]',
    )
    await create_conversation(
        db_session,
        restaurant_id=restaurant_a.id,
        customer_id=customer_a.id,
        channel=ConversationChannel.VOICE,
        transcript='[{"role": "user", "content": "Voz"}]',
    )
    # La de la tenant B y la de canal voice quedan fuera; A/voice no se cruza.
    assert (
        await latest_conversation_transcript(
            db_session,
            restaurant_id=restaurant_a.id,
            customer_id=customer_a.id,
            channel=ConversationChannel.VOICE,
        )
        == '[{"role": "user", "content": "Voz"}]'
    )
    assert (
        await latest_conversation_transcript(
            db_session,
            restaurant_id=restaurant_a.id,
            customer_id=customer_a.id,
            channel=ConversationChannel.WHATSAPP,
        )
        == '[{"role": "user", "content": "Hola"}]'
    )
    # customer_a no tiene conversaciones en la tenant B.
    assert (
        await latest_conversation_transcript(
            db_session,
            restaurant_id=restaurant_b.id,
            customer_id=customer_a.id,
            channel=ConversationChannel.WHATSAPP,
        )
        is None
    )


async def test_latest_conversation_transcript_respects_since(
    db_session, restaurant_factory, customer_factory
):
    """El canal de voz retoma SOLO los turnos de la llamada actual (`since`)."""
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)
    old = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.VOICE,
        transcript='[{"role": "user", "content": "Llamada anterior"}]',
    )
    current = await create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.VOICE,
        transcript='[{"role": "user", "content": "Llamada actual"}]',
    )
    old.date = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    current.date = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    await db_session.flush()

    # `since` tras la llamada vieja excluye su transcript: solo el actual.
    transcript = await latest_conversation_transcript(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        channel=ConversationChannel.VOICE,
        since=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    )
    assert transcript == current.transcript

    # `since` futuro → no hay conversaciones posteriores.
    assert (
        await latest_conversation_transcript(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            channel=ConversationChannel.VOICE,
            since=datetime(2026, 9, 16, 0, 0, tzinfo=UTC),
        )
        is None
    )
