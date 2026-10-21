"""Tests del cliente LLM (`app/agent/client.py`) sin red (httpx.MockTransport)."""

import json

import httpx
import pytest_asyncio
from app.agent.client import ClaudeClient, FakeLLMClient, LLMResponse
from app.agent.tools import tool_schemas


def _message_response(content, *, stop_reason="end_turn"):
    """Sobre de respuesta del Messages API (modelo de SDK 0.121)."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": "claude-haiku-4-5-20251001",
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


@pytest_asyncio.fixture
async def make_client():
    """Fabrica de `ClaudeClient` con MockTransport; captura el body enviado."""

    http_clients: list[httpx.AsyncClient] = []

    def _make(content, *, stop_reason="end_turn"):
        body: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body["request"] = json.loads(request.content)
            return httpx.Response(200, json=_message_response(content, stop_reason=stop_reason))

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_clients.append(http)
        return ClaudeClient(api_key="test-key", http_client=http), body

    yield _make

    for http in http_clients:
        await http.aclose()


async def test_generate_sends_model_and_required_params(make_client):
    client, body = make_client(content=[{"type": "text", "text": "Hola"}])
    response = await client.generate(
        system="Eres el recepcionista",
        messages=[{"role": "user", "content": "Hola"}],
    )
    request = body["request"]
    assert request["model"] == "claude-haiku-4-5-20251001"
    assert request["max_tokens"] == 1024
    assert request["temperature"] == 0.3
    assert request["system"] == "Eres el recepcionista"
    assert request["messages"] == [{"role": "user", "content": "Hola"}]
    assert response.text == "Hola"
    assert response.tool_calls == ()
    assert response.stop_reason == "end_turn"


async def test_generate_sends_tools(make_client):
    client, body = make_client(content=[{"type": "text", "text": "ok"}])
    await client.generate(
        system="s",
        messages=[{"role": "user", "content": "consulta"}],
        tools=tool_schemas(),
    )
    tools = body["request"]["tools"]
    assert tools[0]["name"] == "check_availability"
    assert tools[0]["input_schema"]["type"] == "object"
    assert "properties" in tools[0]["input_schema"]


async def test_generate_without_tools_omits_key(make_client):
    client, body = make_client(content=[{"type": "text", "text": "ok"}])
    await client.generate(system="s", messages=[{"role": "user", "content": "hola"}])
    assert "tools" not in body["request"]


async def test_generate_accepts_overrides(make_client):
    client, body = make_client(content=[{"type": "text", "text": "ok"}])
    await client.generate(system="s", messages=[], max_tokens=2048, temperature=0.0)
    request = body["request"]
    assert request["max_tokens"] == 2048
    assert request["temperature"] == 0.0


async def test_generate_parses_tool_use(make_client):
    client, _body = make_client(
        content=[
            {"type": "text", "text": "Voy a consultar."},
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "check_availability",
                "input": {"date": "2026-09-15", "time": "14:00", "party_size": 2},
            },
        ],
        stop_reason="tool_use",
    )
    response = await client.generate(system="s", messages=[{"role": "user", "content": "x"}])
    assert response.text == "Voy a consultar."
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "toolu_01"
    assert call.name == "check_availability"
    assert call.input["party_size"] == 2
    assert response.stop_reason == "tool_use"


async def test_fake_client_returns_scripted_responses():
    fake = FakeLLMClient([LLMResponse(text="hola", stop_reason="end_turn")])
    response = await fake.generate(system="s", messages=[{"role": "user", "content": "hola"}])
    assert response.text == "hola"
    assert len(fake.calls) == 1
    assert fake.calls[0]["tools"] is None
    # Cola agotada -> respuesta vacia por defecto.
    empty = await fake.generate(system="s", messages=[])
    assert empty.text is None
    assert empty.stop_reason == "end_turn"


async def test_fake_client_streams_scripted_text():
    fake = FakeLLMClient([LLMResponse(text="hola qué tal")])
    chunks = [
        chunk
        async for chunk in fake.generate_stream(system="s", messages=[{"role": "user", "content": "h"}])
    ]
    assert "".join(c.text for c in chunks if c.text).strip() == "hola qué tal"
    assert chunks[-1].response is not None
    assert chunks[-1].response.text == "hola qué tal"


def _sse(events: list[tuple[str, dict]]) -> bytes:
    """Serializa eventos como lo hace el Messages API con `stream=true`."""
    return b"".join(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode() for name, payload in events)


def _stream_body(*, text_deltas: list[str], tool: dict | None = None) -> bytes:
    """Fluye un text block (con deltas) y, si toca, un tool_use con su JSON parcial."""
    events: list[tuple[str, dict]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "claude-haiku-4-5-20251001",
                    "stop_reason": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            },
        ),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("ping", {"type": "ping", "delta": {"type": "ping_delta"}}),
    ]
    for delta in text_deltas:
        events.append(
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": delta},
                },
            )
        )
    events.append(("content_block_stop", {"type": "content_block_stop", "index": 0}))
    if tool is not None:
        events.append(
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": tool["id"],
                        "name": tool["name"],
                        "input": {},
                    },
                },
            )
        )
        for partial in tool["partial_json"]:
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {"type": "input_json_delta", "partial_json": partial},
                    },
                )
            )
        events.append(("content_block_stop", {"type": "content_block_stop", "index": 1}))
    events += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": tool and "tool_use" or "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return _sse(events)


@pytest_asyncio.fixture
async def make_streaming_client():
    """`ClaudeClient` cuyo `stream=true` responde con SSE fijos."""

    http_clients: list[httpx.AsyncClient] = []

    def _make(body: bytes):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=body, headers={"content-type": "text/event-stream"}
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_clients.append(http)
        return ClaudeClient(api_key="test-key", http_client=http)

    yield _make

    for http in http_clients:
        await http.aclose()


async def test_generate_stream_emits_text_deltas_and_final_response(make_streaming_client):
    client = make_streaming_client(_stream_body(text_deltas=["Hola", " qué ", "tal"]))
    chunks = [
        chunk async for chunk in client.generate_stream(system="s", messages=[{"role": "user", "content": "x"}])
    ]
    assert [c.text for c in chunks if c.text] == ["Hola", " qué ", "tal"]
    final = chunks[-1].response
    assert final is not None
    assert final.text == "Hola qué tal"
    assert final.stop_reason == "end_turn"
    assert final.tool_calls == ()


async def test_generate_stream_rebuilds_tool_use_from_json_deltas(make_streaming_client):
    client = make_streaming_client(
        _stream_body(
            text_deltas=["Voy a consultar."],
            tool={
                "id": "toolu_01",
                "name": "check_availability",
                "partial_json": [
                    '{"date": "2026-09-15"',
                    ', "time": "14:00"',
                    ', "party_size": 2}',
                ],
            },
        )
    )
    chunks = [
        chunk async for chunk in client.generate_stream(system="s", messages=[{"role": "user", "content": "x"}])
    ]
    final = chunks[-1].response
    assert final is not None
    assert final.stop_reason == "tool_use"
    call = final.tool_calls[0]
    assert call.id == "toolu_01"
    assert call.input == {"date": "2026-09-15", "time": "14:00", "party_size": 2}
