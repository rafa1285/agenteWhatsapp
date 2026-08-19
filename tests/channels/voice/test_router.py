"""Tests e2e del webhook de voz (cliente ASGI real, form-encoded).

Es la prueba end-to-end local del canal de voz: el form-encoded de Twilio entra
por HTTP, el router resuelve tenant/cliente, el orquestador corre y la respuesta
sale como TwiML XML. Usa `asgi_client` (app real con dependencias overrideadas).
"""

from datetime import date as date_type

from app.agent.client import LLMResponse, ToolCall
from app.channels.voice.models import VoiceCall, VoiceCallStatus
from app.modules.reservations.models import Reservation
from sqlalchemy import func, select

SERVICE_DATE = date_type(2026, 9, 15)


async def _count(session, model) -> int:
    stmt = select(func.count()).select_from(model)
    return await session.scalar(stmt)


def _form(*, call_sid="CA0001", speech_result=None, **overrides: str) -> dict[str, str]:
    fields = {
        "CallSid": call_sid,
        "From": "+34611111111",
        "To": "+34910000001",
    }
    if speech_result is not None:
        fields["SpeechResult"] = speech_result
        fields.setdefault("Confidence", "0.9")
    fields.update(overrides)
    return fields


async def test_initial_call_returns_greeting_twiml(asgi_client, db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number="+34910000001", name="Er Pichi")
    restaurant_id = restaurant.id
    await db_session.commit()
    client, llm, gateway = asgi_client

    response = await client.post("/api/voice/call", data=_form())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "Bienvenido a Er Pichi" in response.text
    assert 'input="speech"' in response.text
    assert llm.calls == []
    assert gateway.sent == []
    row = await db_session.scalar(select(VoiceCall).where(VoiceCall.restaurant_id == restaurant_id))
    assert row is not None
    assert row.status == VoiceCallStatus.IN_PROGRESS


async def test_turn_with_booking_sends_whatsapp_confirmation(
    asgi_client, db_session, availability_setup
):
    restaurant, _tables = await availability_setup()
    restaurant_id = restaurant.id
    await db_session.commit()
    client, llm, gateway = asgi_client
    llm.set_responses(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="t1",
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

    await client.post("/api/voice/call", data=_form())  # saludo
    response = await client.post("/api/voice/call", data=_form(speech_result="Quiero reservar"))

    assert response.status_code == 200
    assert "Listo, tu reserva queda confirmada." in response.text
    assert "<Hangup/>" in response.text
    assert gateway.sent == [{"to": "+34611111111", "text": "Listo, tu reserva queda confirmada."}]
    reservation = await db_session.scalar(
        select(Reservation).where(Reservation.restaurant_id == restaurant_id)
    )
    assert reservation is not None


async def test_unknown_number_returns_courtesy(asgi_client, db_session, restaurant_factory):
    await restaurant_factory(active=True, voice_number="+34910000001")
    await db_session.commit()
    client, llm, gateway = asgi_client

    response = await client.post("/api/voice/call", data=_form(To="+34999999999"))

    assert response.status_code == 200
    assert "no está operativo" in response.text
    assert llm.calls == []
    assert gateway.sent == []
    assert await _count(db_session, VoiceCall) == 0


async def test_status_terminal_updates_row(asgi_client, db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number="+34910000001")
    restaurant_id = restaurant.id
    await db_session.commit()
    client, _llm, _gateway = asgi_client

    await client.post("/api/voice/call", data=_form())  # saludo crea la fila
    response = await client.post(
        "/api/voice/status",
        data=_form(
            CallStatus="completed",
            RecordingUrl="https://api.twilio.com/rec",
            CallDuration="95",
        ),
    )

    assert response.status_code == 200
    row = await db_session.scalar(select(VoiceCall).where(VoiceCall.restaurant_id == restaurant_id))
    assert row.status == VoiceCallStatus.COMPLETED
    assert row.recording_url == "https://api.twilio.com/rec"
    assert row.call_duration == 95


async def test_status_non_terminal_is_noop(asgi_client, db_session, restaurant_factory):
    restaurant = await restaurant_factory(active=True, voice_number="+34910000001")
    restaurant_id = restaurant.id
    await db_session.commit()
    client, _llm, _gateway = asgi_client

    await client.post("/api/voice/call", data=_form())
    await client.post(
        "/api/voice/status", data=_form(CallStatus="ringing", RecordingUrl="https://r")
    )

    row = await db_session.scalar(select(VoiceCall).where(VoiceCall.restaurant_id == restaurant_id))
    assert row.status == VoiceCallStatus.IN_PROGRESS
    assert row.recording_url is None
