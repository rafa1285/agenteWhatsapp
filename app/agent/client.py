"""Cliente LLM abstraído (capa de modelo, §19 del spec).

`LLMClient` es el contrato que permite cambiar de proveedor sin tocar el
orquestador; `ClaudeClient` lo implementa sobre el SDK de Anthropic
(`AsyncAnthropic`, Claude Haiku 4.5); `FakeLLMClient` permite testear sin red.

No construye el bucle de tool-calling: eso es responsabilidad del orquestador
(Fase 4). Este módulo solo serializa la petición y devuelve la respuesta
normalizada (texto + bloques `tool_use`).
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from anthropic import AsyncAnthropic

from app.core.settings import settings


@dataclass(frozen=True)
class ToolCall:
    """Llamada a una tool pedida por el LLM."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """Respuesta normalizada de una generación (texto y/o llamadas a tools)."""

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = None


@dataclass(frozen=True)
class LLMStreamChunk:
    """Un paso del streaming: un delta de texto o, al final, la respuesta completa.

    El último chunk lleva `response` con las `tool_calls` ya reconstruidas (el SDK
    acumula los `input_json_delta`), así que el orquestador no vuelve a parsear.
    """

    text: str | None = None
    response: LLMResponse | None = None


class LLMClient(Protocol):
    """Contrato de la capa de modelo (intercambiable, §19)."""

    async def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse: ...

    async def generate_stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]: ...


class ClaudeClient:
    """Cliente de Claude Haiku 4.5 sobre el SDK de Anthropic.

    El `http_client` es inyectable (httpx) para testear sin red vía
    `MockTransport`. Las excepciones del SDK se propagan: el mapeo a mensajes
    de usuario es responsabilidad del orquestador.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model or settings.AGENT_MODEL
        self._client = AsyncAnthropic(
            api_key=api_key or settings.ANTHROPIC_API_KEY or None,
            http_client=http_client,
            timeout=timeout,
        )

    async def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else settings.AGENT_MAX_TOKENS,
            "temperature": (temperature if temperature is not None else settings.AGENT_TEMPERATURE),
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        message = await self._client.messages.create(**kwargs)
        return _parse_message(message)

    async def generate_stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else settings.AGENT_MAX_TOKENS,
            "temperature": temperature if temperature is not None else settings.AGENT_TEMPERATURE,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            # Solo se reenvían los deltas de texto: los de `input_json` los acumula
            # el SDK y se leen de una vez en el mensaje final.
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield LLMStreamChunk(text=event.delta.text)
            yield LLMStreamChunk(response=_parse_message(await stream.get_final_message()))


def _parse_message(message: Any) -> LLMResponse:
    """Extrae texto y llamadas a tools de la respuesta del Messages API."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in message.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
    return LLMResponse(
        text="".join(text_parts) or None,
        tool_calls=tuple(tool_calls),
        stop_reason=message.stop_reason,
    )


class FakeLLMClient:
    """Cliente scripteado para tests: respuestas en orden, registra llamadas."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._queue: list[LLMResponse] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def set_responses(self, responses: list[LLMResponse]) -> None:
        """Sustituye la cola de respuestas (para fixtures que crean el fake antes)."""
        self._queue[:] = list(responses)

    async def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return self._queue.pop(0) if self._queue else LLMResponse(stop_reason="end_turn")

    async def generate_stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """Mismo guion que `generate`, con el texto troceado en deltas simulados."""
        response = await self.generate(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if response.text:
            for word in response.text.split(" "):
                yield LLMStreamChunk(text=f"{word} ")
        yield LLMStreamChunk(response=response)
