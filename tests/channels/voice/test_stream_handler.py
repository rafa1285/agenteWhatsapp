"""Tests del Media Stream de voz: troceo de frases y protocolo con Twilio.

Nada toca Deepgram, ElevenLabs ni Claude: el STT, el TTS y el WebSocket de Twilio
se sustituyen por dobles, así que se puede verificar el contrato real del stream
(`media` con su `streamSid`, `clear` en el barge-in) y la integración con el
orquestador en streaming con `FakeLLMClient`.
"""

import asyncio
import base64
import json
from collections.abc import AsyncGenerator

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import select

from app.agent.client import FakeLLMClient, LLMResponse
from app.agent.models import Conversation
from app.channels.voice.stream_handler import VoiceStreamHandler, split_first_sentence
from app.channels.whatsapp.gateway import FakeWhatsAppGateway
from app.core.settings import settings

STREAM_SID = "MZ1234567890"
CALLER = "+34611111111"


# ------------------------------------------------------------------ troceo de frases


def test_splits_at_the_first_closed_sentence():
    sentence, rest = split_first_sentence(
        "Buenas tardes, tenemos mesa disponible ahora. ¿Te la reservo?"
    )
    assert sentence == "Buenas tardes, tenemos mesa disponible ahora."
    assert rest == "¿Te la reservo?"


def test_waits_for_a_short_sentence_to_finish():
    # "Sí." tiene menos de _MIN_SENTENCE_CHARS: hablar tan corto suena a robot.
    assert split_first_sentence("Sí.") == (None, "Sí.")
    assert split_first_sentence("Sí, claro que sí, hay mesa.") == (
        "Sí, claro que sí, hay mesa.",
        "",
    )


def test_cuts_long_runs_without_a_period():
    buffer = " ".join(["palabra"] * 40)
    sentence, rest = split_first_sentence(buffer)
    assert sentence is not None and len(sentence) < len(buffer)
    assert sentence + " " + rest == buffer  # no se pierde texto al cortar


# ------------------------------------------------------------------- dobles de prueba


class _FakeWebSocket:
    """Media Stream de Twilio simulado: cola de eventos entrantes y frames salientes."""

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = False

    def feed(self, event: dict) -> None:
        self.incoming.put_nowait(json.dumps(event))

    async def receive_text(self) -> str:
        return await self.incoming.get()

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def close(self) -> None:
        self.closed = True


class _FakeSTT:
    """Deepgram simulado: guarda el audio recibido y expone las callbacks del handler."""

    instances: list["_FakeSTT"] = []

    def __init__(self, *, on_transcript, on_speech_started=None) -> None:
        self.on_transcript = on_transcript
        self.on_speech_started = on_speech_started
        self.audio: list[bytes] = []
        type(self).instances.append(self)

    async def __aenter__(self) -> "_FakeSTT":
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def send_audio(self, audio: bytes) -> None:
        self.audio.append(audio)


def _fake_tts(monkeypatch) -> list[str]:
    """Sustituye ElevenLabs: devuelve la lista de textos que se pidieron hablar."""
    spoken: list[str] = []

    async def _stream(text: str, **_kwargs):
        spoken.append(text)
        for _ in range(2):
            yield b"\x00\x01"

    monkeypatch.setattr(
        "app.channels.voice.stream_handler.elevenlabs_tts_service.text_to_speech_stream", _stream
    )
    return spoken


def _session_factory(session) -> object:
    async def _gen() -> AsyncGenerator:
        yield session

    return _gen


def _handler(websocket, db_session, llm, restaurant, customer_id=None) -> VoiceStreamHandler:
    return VoiceStreamHandler(
        websocket=websocket,
        session_factory=_session_factory(db_session),
        llm=llm,
        gateway=FakeWhatsAppGateway(),
        restaurant=restaurant,
        customer_id=customer_id,
    )


@pytest.fixture
def fake_stt(monkeypatch):
    _FakeSTT.instances.clear()
    monkeypatch.setattr("app.channels.voice.stream_handler.DeepgramStreamSTT", _FakeSTT)
    yield
    _FakeSTT.instances.clear()


# --------------------------------------------------------------------- pipeline completo


async def test_stream_call_greets_answers_and_closes(
    db_session, restaurant_factory, monkeypatch, fake_stt
):
    spoken = _fake_tts(monkeypatch)
    restaurant = await restaurant_factory(name="Er Pichi")
    ws = _FakeWebSocket()
    llm = FakeLLMClient(
        [
            LLMResponse(
                text="Sí, tenemos mesa a las 14:00. ¿La reservo para dos personas esta noche?"
            )
        ]
    )
    handler = _handler(ws, db_session, llm, restaurant)

    running = asyncio.create_task(handler.handle())
    await asyncio.sleep(0.05)
    ws.feed({"event": "start", "start": {"streamSid": STREAM_SID, "caller": CALLER}})
    ws.feed({"event": "media", "media": {"payload": base64.b64encode(b"mulaw-audio").decode()}})
    await asyncio.sleep(0.05)

    stt = _FakeSTT.instances[0]
    assert stt.audio == [b"mulaw-audio"]  # el audio de Twilio llega a Deepgram decodificado

    await stt.on_transcript("¿Tenéis mesa a las 14?", 0.95)
    await asyncio.sleep(0.2)

    events = [frame["event"] for frame in ws.sent]
    # Cada frame de audio lleva su streamSid: sin él Twilio lo descarta y el
    # cliente no oye nada (el fallo que tenía esta ruta).
    media = [frame for frame in ws.sent if frame["event"] == "media"]
    assert media, f"no se habló: {events}"
    assert all(frame["streamSid"] == STREAM_SID for frame in media)
    assert "mark" in events and "speech_start" in json.dumps(ws.sent)
    # Primero el saludo con el aviso RGPD, y la respuesta llegó troceada por frases
    # (dos síntesis), no junta en un solo bloque.
    assert "Bienvenido a Er Pichi" in spoken[0] and "grabada" in spoken[0]
    assert spoken[1:] == [
        "Sí, tenemos mesa a las 14:00.",
        "¿La reservo para dos personas esta noche?",
    ]

    conversation = await db_session.scalar(select(Conversation).order_by(Conversation.date))
    assert conversation is not None
    assert "mesa a las 14:00" in conversation.transcript

    ws.feed({"event": "stop"})
    await asyncio.wait_for(running, timeout=2)
    assert handler._transcript == conversation.transcript  # memoria para el siguiente turno


async def test_stream_call_reasks_on_low_confidence(
    db_session, restaurant_factory, monkeypatch, fake_stt
):
    restaurant = await restaurant_factory()
    ws = _FakeWebSocket()
    llm = FakeLLMClient()
    spoken = _fake_tts(monkeypatch)
    handler = _handler(ws, db_session, llm, restaurant)

    running = asyncio.create_task(handler.handle())
    ws.feed({"event": "start", "start": {"streamSid": STREAM_SID, "caller": CALLER}})
    await asyncio.sleep(0.1)
    assert "Bienvenido a" in spoken[0]  # el saludo lo pone ElevenLabs, no el <Say> de Twilio

    await _FakeSTT.instances[0].on_transcript(
        "meh meh", settings.VOICE_STT_CONFIDENCE_THRESHOLD / 2
    )
    await asyncio.sleep(0.1)

    assert llm.calls == []  # confianza baja: no se molestó al modelo (§10.5)
    assert "no te he entendido" in " ".join(spoken)

    ws.feed({"event": "stop"})
    await asyncio.wait_for(running, timeout=2)


# ------------------------------------------------------------------------- barge-in


async def test_barge_in_clears_twilio_and_drops_queued_sentences(
    db_session, restaurant_factory, fake_stt
):
    restaurant = await restaurant_factory()
    ws = _FakeWebSocket()
    handler = _handler(ws, db_session, FakeLLMClient(), restaurant)
    handler._stream_sid = STREAM_SID
    handler._speaking = True

    await handler._speak("Primera frase que ya se está oyendo ahora mismo.")
    await handler._speak("Segunda frase que ainda no sonó.")
    await handler._on_speech_started()

    assert handler._speak_queue.empty()
    assert [frame["event"] for frame in ws.sent] == ["clear"]
    assert ws.sent[0]["streamSid"] == STREAM_SID


async def test_interrupted_synthesis_stops_sending_audio(db_session, restaurant_factory, fake_stt):
    restaurant = await restaurant_factory()
    ws = _FakeWebSocket()
    handler = _handler(ws, db_session, FakeLLMClient(), restaurant)
    handler._stream_sid = STREAM_SID
    handler._interrupted = True

    await handler._synthesize("Frase que el cliente ya cortó.")

    assert [frame["event"] for frame in ws.sent] == ["mark", "mark"]  # start y end, sin audio
