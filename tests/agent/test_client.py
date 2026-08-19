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
