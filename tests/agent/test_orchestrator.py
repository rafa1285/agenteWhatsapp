"""Tests del orquestador de conversación (bucle de tool-calling, BD real).

`run_conversation` se testea con `FakeLLMClient` scripteado (sin red); las tools
reales se ejecutan contra la BD de tests dentro de `db_session` (nunca commitea).
"""

import json
from datetime import date as date_type

from app.agent.client import FakeLLMClient, LLMResponse, ToolCall
from app.agent.models import Conversation, ConversationOutcome, Escalation, EscalationReason
from app.agent.orchestrator import (
    FALLBACK_TEXT,
    TECHNICAL_FAILURE_TEXT,
    build_system_prompt,
    run_conversation,
)
from app.core.models import Restaurant
from app.modules.reservations.models import Reservation, SourceChannel
from sqlalchemy import func, select

SERVICE_DATE = date_type(2026, 9, 15)


class _RaisingClient:
    """Fake que simula un fallo del LLM (SDK/red caídos)."""

    async def generate(self, **kwargs):
        raise RuntimeError("llm down")


def test_build_system_prompt_uses_tone_and_channel() -> None:
    restaurant = Restaurant(
        name="Er Pichi de Cai",
        public_phone="+34910000000",
        whatsapp_number_id="wa-1",
        voice_number="+34910000001",
        prompt_tone="con gracia andaluza",
    )
    prompt = build_system_prompt(restaurant=restaurant, source_channel=SourceChannel.WHATSAPP)
    assert "Er Pichi de Cai" in prompt
    assert "con gracia andaluza" in prompt
    assert "whatsapp" in prompt


async def test_text_only_query(db_session, restaurant_factory, customer_factory):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id)
    fake = FakeLLMClient([LLMResponse(text="¡Buenas! ¿En qué te ayudo?")])
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Hola, ¿tenéis mesa esta noche?",
        customer_id=customer.id,
    )
    assert result.outcome == ConversationOutcome.QUERY
    assert result.text == "¡Buenas! ¿En qué te ayudo?"
    assert result.tool_calls == 0
    # Conversación persistida con transcript de texto (usuario + agente).
    conversation = await db_session.get(Conversation, result.conversation_id)
    assert conversation is not None
    turns = json.loads(conversation.transcript)
    assert turns[0] == {"role": "user", "content": "Hola, ¿tenéis mesa esta noche?"}
    assert turns[-1]["role"] == "assistant"
    assert conversation.outcome == ConversationOutcome.QUERY


async def test_tool_calling_check_availability(db_session, availability_setup):
    restaurant, _tables = await availability_setup()
    fake = FakeLLMClient(
        [
            LLMResponse(
                text="Voy a consultar la disponibilidad.",
                tool_calls=(
                    ToolCall(
                        id="toolu_01",
                        name="check_availability",
                        input={
                            "date": SERVICE_DATE.isoformat(),
                            "time": "14:00",
                            "party_size": 2,
                        },
                    ),
                ),
            ),
            LLMResponse(text="Tenemos mesa libre a las 14:00."),
        ]
    )
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="¿Tenéis hueco para dos el martes a las 14:00?",
    )
    assert result.outcome == ConversationOutcome.QUERY
    assert result.text == "Tenemos mesa libre a las 14:00."
    assert result.tool_calls == 1
    # El histórico reenviado en la 2ª llamada incluye el tool_use y su tool_result.
    second = fake.calls[1]["messages"]
    assistant = next(m for m in second if m["role"] == "assistant")
    assert assistant["content"][0]["type"] == "text"
    assert assistant["content"][1] == {
        "type": "tool_use",
        "id": "toolu_01",
        "name": "check_availability",
        "input": {"date": "2026-09-15", "time": "14:00", "party_size": 2},
    }
    tool_user = next(m for m in second if m["role"] == "user" and isinstance(m["content"], list))
    block = tool_user["content"][0]
    assert block["type"] == "tool_result"
    payload = json.loads(block["content"])
    assert payload["available"] is True


async def test_create_booking_reservation_created(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context()
    fake = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="toolu_01",
                        name="create_booking",
                        input={
                            "date": SERVICE_DATE.isoformat(),
                            "time": "14:00",
                            "party_size": 2,
                        },
                    ),
                ),
            ),
            LLMResponse(text="Listo, tu reserva queda confirmada."),
        ]
    )
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Quiero reservar mesa para dos el martes a las 14:00.",
        customer_id=customer.id,
    )
    assert result.outcome == ConversationOutcome.RESERVATION_CREATED
    reservation = await db_session.scalar(select(Reservation))
    assert reservation is not None
    assert reservation.customer_id == customer.id
    assert reservation.restaurant_id == restaurant.id


async def test_large_group_escalation(db_session, reservation_context):
    restaurant, customer, _tables = await reservation_context(
        restaurant_overrides={"large_group_threshold": 8}, tables=((1, 12),)
    )
    fake = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="toolu_01",
                        name="create_booking",
                        input={
                            "date": SERVICE_DATE.isoformat(),
                            "time": "14:00",
                            "party_size": 10,
                        },
                    ),
                ),
            ),
            LLMResponse(text="Te confirmo en un momento, el equipo lo revisa."),
        ]
    )
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Quiero reservar para 10 personas.",
        customer_id=customer.id,
    )
    assert result.outcome == ConversationOutcome.ESCALATED
    assert result.escalation_id is not None
    escalation = await db_session.get(Escalation, result.escalation_id)
    assert escalation is not None
    assert escalation.reason == EscalationReason.LARGE_GROUP
    assert escalation.conversation_id == result.conversation_id


async def test_escalate_complaint(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    fake = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="toolu_01",
                        name="escalate",
                        input={
                            "reason": "complaint",
                            "summary": "El cliente está muy enfadado con el retraso",
                        },
                    ),
                ),
            ),
            LLMResponse(text="Entiendo. Te pongo con el equipo del restaurante."),
        ]
    )
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Estoy muy enfadada, esto es inadmisible.",
    )
    assert result.outcome == ConversationOutcome.COMPLAINT
    assert result.escalation_id is not None
    escalation = await db_session.get(Escalation, result.escalation_id)
    assert escalation.reason == EscalationReason.COMPLAINT
    # La tool escalate creó la fila; el orquestador no duplica la escalación.
    count = await db_session.scalar(select(func.count()).select_from(Escalation))
    assert count == 1


async def test_technical_failure_escalates(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    result = await run_conversation(
        db_session,
        llm=_RaisingClient(),
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="¿Tenéis hueco mañana?",
    )
    assert result.text == TECHNICAL_FAILURE_TEXT
    assert result.outcome == ConversationOutcome.ESCALATED
    assert result.escalation_id is not None
    escalation = await db_session.get(Escalation, result.escalation_id)
    assert escalation.reason == EscalationReason.TECHNICAL_FAILURE


async def test_max_iterations_exhausted(db_session, availability_setup):
    restaurant, _tables = await availability_setup()
    tool_response = LLMResponse(
        tool_calls=(
            ToolCall(
                id="toolu_0",
                name="check_availability",
                input={"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
            ),
        ),
    )
    fake = FakeLLMClient([tool_response] * 5)
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Hola",
        max_iterations=5,
    )
    assert result.text == FALLBACK_TEXT
    assert result.outcome == ConversationOutcome.QUERY
    assert result.tool_calls == 5


async def test_resume_with_prior_transcript(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    prior = json.dumps(
        [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Buenas, ¿en qué te ayudo?"},
        ]
    )
    fake = FakeLLMClient([LLMResponse(text="Claro, dime el día.")])
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Quiero una mesa para dos.",
        prior_transcript=prior,
    )
    # Los turnos previos se reenvían al LLM y se conservan en el transcript final.
    first = fake.calls[0]["messages"]
    assert first[0] == {"role": "user", "content": "Hola"}
    assert first[1] == {"role": "assistant", "content": "Buenas, ¿en qué te ayudo?"}
    assert first[2] == {"role": "user", "content": "Quiero una mesa para dos."}
    turns = json.loads(result.transcript)
    assert [t["content"] for t in turns] == [
        "Hola",
        "Buenas, ¿en qué te ayudo?",
        "Quiero una mesa para dos.",
        "Claro, dime el día.",
    ]


async def test_customer_memory_in_prompt(db_session, restaurant_factory, customer_factory):
    restaurant = await restaurant_factory()
    customer = await customer_factory(restaurant.id, name="María", phone="+34611111111")
    customer.preferred_language = "en"
    await db_session.flush()
    fake = FakeLLMClient([LLMResponse(text="ok")])
    await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Hi",
        customer_id=customer.id,
    )
    system = fake.calls[0]["system"]
    assert "María" in system
    assert "en" in system


async def test_customer_of_other_tenant_not_in_memory(
    db_session, restaurant_factory, customer_factory
):
    restaurant = await restaurant_factory(name="Rest A")
    other = await restaurant_factory(name="Rest B")
    other_customer = await customer_factory(other.id, name="Juan")
    fake = FakeLLMClient([LLMResponse(text="ok")])
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Hola",
        customer_id=other_customer.id,
    )
    assert "Juan" not in fake.calls[0]["system"]
    # El id del cliente de otra tenant no se arrastra a la conversación.
    conversation = await db_session.get(Conversation, result.conversation_id)
    assert conversation.customer_id is None


async def test_unknown_tool_is_error(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    fake = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(id="toolu_01", name="no_existe", input={}),)),
            LLMResponse(text="Hecho."),
        ]
    )
    result = await run_conversation(
        db_session,
        llm=fake,
        restaurant=restaurant,
        source_channel=SourceChannel.WHATSAPP,
        incoming_message="Haz lo imposible.",
    )
    assert result.outcome == ConversationOutcome.QUERY
    second = fake.calls[1]["messages"]
    tool_user = next(m for m in second if m["role"] == "user" and isinstance(m["content"], list))
    block = tool_user["content"][0]
    assert block["type"] == "tool_result"
    assert block["is_error"] is True
