"""Tests del handler del canal de voz (máquina de estados del turno).

Llaman a `process_voice_call` / `process_voice_status` directamente (sin HTTP)
con la sesión de tests, `FakeLLMClient` y `FakeWhatsAppGateway`. El handler hace
`commit`: cada test arranca con la BD vacía (fixture `db_session`). El saludo
(primer POST del CallSid) crea y commitea la fila `voice_calls`; los turnos
posteriores reutilizan el mismo CallSid.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.agent.client import FakeLLMClient, LLMResponse, ToolCall
from app.agent.models import Conversation, ConversationChannel, Escalation
from app.agent.orchestrator import FALLBACK_TEXT
from app.agent.service import create_conversation
from app.channels.voice.handler import (
    COURTESY_TEXT,
    LOW_CONFIDENCE_TEXT,
    REPROMPT_TEXT,
    SECOND_SILENCE_TEXT,
    TRANSFER_FAILED_TEXT,
    process_voice_call,
    process_voice_status,
)
from app.channels.voice.models import VoiceCall, VoiceCallStatus
from app.channels.voice.schemas import TwilioCallRequest
from app.channels.whatsapp.gateway import FakeWhatsAppGateway
from app.modules.customers.models import Customer
from app.modules.reservations.models import Reservation, SourceChannel
from sqlalchemy import func, select

DEFAULT_SID = "CA0001"
VOICE_NUMBER = "+34910000001"
BOOKING = {"date": "2026-09-15", "time": "14:00", "party_size": 2}


def _call(**overrides: str) -> TwilioCallRequest:
    """Form realista de Twilio (CallSid/From/To + extras)."""
    fields = {
        "CallSid": DEFAULT_SID,
        "From": "+34611111111",
        "To": VOICE_NUMBER,
    }
    fields.update(overrides)
    return TwilioCallRequest.from_form(fields)


async def _count(session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return await session.scalar(stmt)


async def _call_row(session, *, call_sid: str = DEFAULT_SID) -> VoiceCall | None:
    return await session.scalar(select(VoiceCall).where(VoiceCall.call_sid == call_sid))


def _escalate_responses(text: str = "Entiendo, un responsable te contacta en breve."):
    return [
        LLMResponse(
            tool_calls=(
                ToolCall(
                    id="t1",
                    name="escalate",
                    input={
                        "reason": "complaint",
                        "summary": "El cliente quiere hablar con un responsable",
                    },
                ),
            ),
        ),
        LLMResponse(text=text),
    ]


def _booking_responses(text: str = "Listo, tu reserva queda confirmada."):
    return [
        LLMResponse(tool_calls=(ToolCall(id="t1", name="create_booking", input=dict(BOOKING)),)),
        LLMResponse(text=text),
    ]


async def test_unknown_number_gets_courtesy_and_no_rows(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    twiml = await process_voice_call(
        db_session, request=_call(To="+34999999999"), llm=llm, gateway=gateway
    )

    assert COURTESY_TEXT in twiml
    assert llm.calls == []
    assert gateway.sent == []
    assert await _count(db_session, VoiceCall, restaurant_id=restaurant_id) == 0
    assert await _count(db_session, Conversation, restaurant_id=restaurant_id) == 0


async def test_inactive_tenant_gets_courtesy(db_session, restaurant_factory):
    await restaurant_factory(active=False, voice_number=VOICE_NUMBER)
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    twiml = await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)

    assert COURTESY_TEXT in twiml
    assert llm.calls == []
    assert gateway.sent == []


async def test_initial_call_creates_greeting_with_rgpd_notice(db_session, restaurant_factory):
    await restaurant_factory(active=True, voice_number=VOICE_NUMBER, name="Er Pichi")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    twiml = await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)

    assert "Bienvenido a Er Pichi" in twiml
    assert "puede ser grabada" in twiml  # aviso de grabación RGPD obligatorio al inicio
    assert 'input="speech"' in twiml
    assert "/api/voice/call" in twiml
    assert llm.calls == []
    assert gateway.sent == []
    row = await _call_row(db_session)
    assert row is not None
    assert row.status == VoiceCallStatus.IN_PROGRESS
    assert row.silence_count == 0


async def test_first_silence_reprompts(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)

    assert REPROMPT_TEXT in twiml
    row = await _call_row(db_session)
    assert row.silence_count == 1
    assert row.status == VoiceCallStatus.IN_PROGRESS
    assert llm.calls == []
    assert await _count(db_session, Conversation, restaurant_id=restaurant_id) == 0


async def test_second_silence_hangs_up_and_marks_incomplete(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)

    assert SECOND_SILENCE_TEXT in twiml
    assert "<Hangup/>" in twiml
    row = await _call_row(db_session)
    assert row.status == VoiceCallStatus.INCOMPLETE
    assert row.completed_at is not None
    assert await _count(db_session, Conversation, restaurant_id=restaurant_id) == 0


async def test_low_confidence_reprompts_without_llm(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session,
        request=_call(SpeechResult="no lo sé", Confidence="0.3"),
        llm=llm,
        gateway=gateway,
    )

    assert LOW_CONFIDENCE_TEXT in twiml
    assert llm.calls == []
    assert await _count(db_session, Conversation, restaurant_id=restaurant_id) == 0


async def test_turn_creates_voice_conversation_and_gathers_next(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session, request=_call(SpeechResult="Hola", Confidence="0.9"), llm=llm, gateway=gateway
    )

    assert FALLBACK_TEXT in twiml
    assert 'input="speech"' in twiml  # sigue la conversación con otro Gather
    assert len(llm.calls) == 1
    assert llm.calls[0]["messages"][-1]["content"] == "Hola"
    assert "voice" in llm.calls[0]["system"]
    conversation = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant_id)
    )
    assert conversation is not None
    assert conversation.channel == ConversationChannel.VOICE


async def test_prior_transcript_is_scoped_to_current_call(
    db_session, restaurant_factory, customer_factory
):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    customer = await customer_factory(restaurant_id, phone="34611111111")
    # Conversación vieja de una llamada anterior (antes del inicio de esta).
    old = await create_conversation(
        db_session,
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        channel=ConversationChannel.VOICE,
        transcript='[{"role": "user", "content": "Llamada anterior"}]',
    )
    old.date = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    await db_session.flush()

    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()
    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    await process_voice_call(
        db_session, request=_call(SpeechResult="Hola", Confidence="0.9"), llm=llm, gateway=gateway
    )
    await process_voice_call(
        db_session,
        request=_call(SpeechResult="¿Hay mesa para dos?", Confidence="0.9"),
        llm=llm,
        gateway=gateway,
    )

    # El segundo turno retoma el transcript del turno 1 de ESTA llamada (desde
    # `voice_call.created_at`), no el de la llamada anterior del cliente.
    messages = llm.calls[1]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "Hola"
    assert messages[2]["content"] == "¿Hay mesa para dos?"
    assert all(m.get("content") != "Llamada anterior" for m in messages)


async def test_booking_sends_whatsapp_confirmation(db_session, availability_setup):
    restaurant, _tables = await availability_setup()
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()
    llm.set_responses(_booking_responses())

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session,
        request=_call(SpeechResult="Quiero reservar", Confidence="0.9"),
        llm=llm,
        gateway=gateway,
    )

    assert "Listo, tu reserva queda confirmada." in twiml
    assert "<Hangup/>" in twiml
    assert gateway.sent == [{"to": "+34611111111", "text": "Listo, tu reserva queda confirmada."}]
    reservation = await db_session.scalar(
        select(Reservation).where(Reservation.restaurant_id == restaurant_id)
    )
    assert reservation is not None
    assert reservation.source_channel == SourceChannel.VOICE
    row = await _call_row(db_session)
    assert row.confirmation_sent is True


async def test_whatsapp_confirmation_sent_once_per_call(db_session, availability_setup):
    restaurant, _tables = await availability_setup()
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    # Simula una confirmación ya enviada en un turno anterior de la misma llamada.
    row = await _call_row(db_session)
    row.confirmation_sent = True
    await db_session.commit()

    llm.set_responses(_booking_responses())
    await process_voice_call(
        db_session,
        request=_call(SpeechResult="Quiero reservar", Confidence="0.9"),
        llm=llm,
        gateway=gateway,
    )

    assert gateway.sent == []
    assert await _count(db_session, Reservation, restaurant_id=restaurant_id) == 1


async def test_complaint_without_transfer_escalates_and_hangs_up(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()
    llm.set_responses(_escalate_responses())

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session,
        request=_call(SpeechResult="Quiero hablar con el encargado", Confidence="0.9"),
        llm=llm,
        gateway=gateway,
    )

    assert "<Hangup/>" in twiml
    assert "<Dial" not in twiml
    escalation = await db_session.scalar(
        select(Escalation).where(Escalation.restaurant_id == restaurant_id)
    )
    assert escalation is not None
    assert escalation.reason.value == "complaint"


async def test_complaint_with_transfer_dials(db_session, restaurant_factory):
    # Ventana que contiene el instante actual → transferencia procede.
    now_madrid = datetime.now(UTC).astimezone(ZoneInfo("Europe/Madrid"))
    await restaurant_factory(
        active=True,
        voice_number=VOICE_NUMBER,
        live_transfer_enabled=True,
        transfer_phone="+34910000002",
        transfer_hours=[{"weekday": now_madrid.weekday(), "start": "00:00", "end": "23:59"}],
    )
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()
    llm.set_responses(_escalate_responses())

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session,
        request=_call(SpeechResult="Quiero hablar con el encargado", Confidence="0.9"),
        llm=llm,
        gateway=gateway,
    )

    assert "<Dial" in twiml
    assert 'timeout="15"' in twiml
    assert "+34910000002" in twiml
    assert "/api/voice/call" in twiml  # action del Dial


async def test_transfer_outside_hours_does_not_dial(db_session, restaurant_factory):
    restaurant = await restaurant_factory(
        active=True,
        voice_number=VOICE_NUMBER,
        live_transfer_enabled=True,
        transfer_phone="+34910000002",
        transfer_hours=[],  # sin ventana → nunca transfiere
    )
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()
    llm.set_responses(_escalate_responses())

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session,
        request=_call(SpeechResult="Quiero hablar con el encargado", Confidence="0.9"),
        llm=llm,
        gateway=gateway,
    )

    assert "<Dial" not in twiml
    assert "<Hangup/>" in twiml
    assert await _count(db_session, Escalation, restaurant_id=restaurant_id) == 1


async def test_dial_completion_answered_marks_transferred(db_session, restaurant_factory):
    await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session, request=_call(DialCallStatus="answered"), llm=llm, gateway=gateway
    )

    assert "<Response></Response>" in twiml  # <Response/> vacío: Twilio ya gestiona la llamada
    row = await _call_row(db_session)
    assert row.status == VoiceCallStatus.TRANSFERRED
    assert row.completed_at is not None


async def test_dial_completion_no_answer_hangs_up(db_session, restaurant_factory):
    await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    twiml = await process_voice_call(
        db_session, request=_call(DialCallStatus="no-answer"), llm=llm, gateway=gateway
    )

    assert TRANSFER_FAILED_TEXT in twiml
    assert "<Hangup/>" in twiml
    row = await _call_row(db_session)
    assert row.status == VoiceCallStatus.INCOMPLETE


async def test_status_terminal_updates_row(db_session, restaurant_factory):
    await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    await process_voice_status(
        db_session,
        request=_call(
            CallStatus="completed",
            RecordingUrl="https://api.twilio.com/rec1",
            CallDuration="95",
        ),
    )

    row = await _call_row(db_session)
    assert row.status == VoiceCallStatus.COMPLETED
    assert row.recording_url == "https://api.twilio.com/rec1"
    assert row.call_duration == 95
    assert row.completed_at is not None


async def test_status_non_terminal_is_noop(db_session, restaurant_factory):
    await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    await process_voice_status(
        db_session, request=_call(CallStatus="ringing", RecordingUrl="https://api.twilio.com/rec2")
    )

    row = await _call_row(db_session)
    assert row.status == VoiceCallStatus.IN_PROGRESS
    assert row.recording_url is None


async def test_status_for_unknown_call_creates_row(db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id

    await process_voice_status(
        db_session, request=_call(CallSid="CA-solo-status", CallStatus="completed")
    )

    row = await _call_row(db_session, call_sid="CA-solo-status")
    assert row is not None
    assert row.restaurant_id == restaurant_id
    assert row.customer_id is None
    assert row.status == VoiceCallStatus.COMPLETED


async def test_repeat_caller_reuses_customer(db_session, restaurant_factory, customer_factory):
    restaurant = await restaurant_factory(active=True, voice_number=VOICE_NUMBER)
    restaurant_id = restaurant.id
    existing = await customer_factory(restaurant_id, phone="34611111111", name="Ana")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    await process_voice_call(
        db_session, request=_call(SpeechResult="Hola", Confidence="0.9"), llm=llm, gateway=gateway
    )

    assert await _count(db_session, Customer, restaurant_id=restaurant_id) == 1
    conversation = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant_id)
    )
    assert conversation.customer_id == existing.id
    row = await _call_row(db_session)
    assert row.customer_id == existing.id
    assert "Ana" in llm.calls[0]["system"]


async def test_call_for_one_restaurant_does_not_touch_other(db_session, restaurant_factory):
    restaurant_a = await restaurant_factory(active=True, voice_number=VOICE_NUMBER, name="Rest A")
    restaurant_b = await restaurant_factory(active=True, voice_number="+34920000001", name="Rest B")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_voice_call(db_session, request=_call(), llm=llm, gateway=gateway)
    await process_voice_call(
        db_session, request=_call(SpeechResult="Hola", Confidence="0.9"), llm=llm, gateway=gateway
    )

    assert await _count(db_session, Conversation, restaurant_id=restaurant_a.id) == 1
    assert await _count(db_session, Conversation, restaurant_id=restaurant_b.id) == 0
    assert await _count(db_session, VoiceCall, restaurant_id=restaurant_a.id) == 1
    assert await _count(db_session, VoiceCall, restaurant_id=restaurant_b.id) == 0
