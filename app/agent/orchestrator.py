"""Orquestador de conversación (Fase 4): bucle de tool-calling.

Recibe un mensaje entrante con el contexto ya resuelto por el canal (webhook de
WhatsApp, canal de voz), itera LLM + tools hasta una respuesta final, y persiste
`Conversation` y `Escalation`. Es lógica pura, reutilizable por los canales y el
panel; no conoce el transporte (no hay routers aquí).

Reglas del spec que materializa: bucle LLM+tools+memoria (§18.6), prompt de
sistema base (§18.4), escalación por grupo grande (§9.7), queja/tono negativo
(§9.8), fallo técnico (§9.11), multi-idioma (§8.3), naturalidad (§12) y memoria
de cliente recurrente (§12). El número máximo de iteraciones y el formato del
transcript son decisiones propias (el spec no los define).
"""

import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient, LLMResponse, ToolCall
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
    transcript_from_json,
    transcript_to_json,
)
from app.agent.tool import ToolContext
from app.agent.tools import tool_by_name, tool_schemas
from app.core.models import Restaurant
from app.modules.customers.models import Customer
from app.modules.reservations.models import SourceChannel

#: Texto neutro cuando el agente no produce respuesta (agota iteraciones o
#: devuelve texto vacío).
FALLBACK_TEXT = (
    "Perdona, no he podido terminar de atenderte. Un momento de paciencia; "
    "te respondo en un instante."
)

#: Mensaje de respaldo ante un fallo técnico (§9.11 del spec).
TECHNICAL_FAILURE_TEXT = (
    "Ups, estoy teniendo un problema técnico. Un miembro del equipo te contacta "
    "en un momento para ayudarte."
)


@dataclass(frozen=True)
class ConversationResult:
    """Resultado de una iteración de conversación (texto + estado persistido)."""

    text: str
    outcome: ConversationOutcome
    conversation_id: uuid.UUID
    escalation_id: uuid.UUID | None = None
    transcript: str = "[]"
    tool_calls: int = 0


def build_system_prompt(
    *,
    restaurant: Restaurant,
    customer: Customer | None = None,
    source_channel: SourceChannel,
) -> str:
    """Prompt de sistema base (§18.4) + tono del restaurante + memoria de cliente.

    Cubre las reglas de las secciones 7.1 (tono), 8.3 (idioma), 9 (reservas,
    grupos grandes, quejas, cancelación, fuera de dominio) y 12 (naturalidad y
    memoria de cliente recurrente) del spec.
    """
    tone = restaurant.prompt_tone or "cercano y profesional"
    lines = [
        f"Eres el recepcionista automático de {restaurant.name}. Atiendes reservas "
        f"y preguntas frecuentes por {source_channel.value} 24/7.",
        "Usa las herramientas disponibles para consultar disponibilidad, crear, "
        "modificar o cancelar reservas y responder preguntas. Nunca inventes datos: "
        "si no los tienes, usa una herramienta o deriva.",
        f"Estilo: {tone}.",
        "Para reservar: pide fecha, hora y número de comensales; consulta la "
        "disponibilidad; crea la reserva; y confirma con el resumen que devuelve "
        "la herramienta.",
        "Los grupos por encima del umbral del restaurante no se autoconfirman: el "
        "sistema los deriva a una persona del equipo; comunícalo y di que les "
        "confirmarán en breve.",
        "Si el cliente muestra una queja o un tono negativo, usa la herramienta "
        "escalate con motivo complaint de inmediato: no intentes resolverlo tú.",
        "Para cancelar una reserva exige confirmación explícita del cliente "
        "(confirmed=true); nunca canceles sin ella.",
        "Si la petición está fuera de tu ámbito, deriva con amabilidad y ofrece "
        "ayuda en lo que sí puedes; nunca ignores.",
        "Responde siempre en el idioma del cliente. Sé natural y conversacional: "
        "nunca suenes como una base de datos ('según mis registros...').",
        "Cuando una herramienta devuelva ok=False, transmite la razón al cliente "
        "con naturalidad y propón una alternativa si la hay.",
    ]
    if customer is not None:
        if customer.name:
            lines.append(f"El cliente que está hablando es {customer.name}: trátalo con cercanía.")
        if customer.preferred_language:
            lines.append(
                f"Idioma preferido del cliente: {customer.preferred_language}. "
                "Úsalo si no está claro por el mensaje."
            )
        if customer.last_complaint_date:
            lines.append(
                "Este cliente tuvo una queja reciente: ten especial cuidado y comprensión con él."
            )
    return "\n".join(lines)


def _text_turns(messages: list[dict]) -> list[dict]:
    """Extrae los turnos de texto (user string + assistant text) del histórico.

    Descarta los bloques tool_use/tool_result: no forman parte del transcript
    legible y reenviarlos al resume rompería el protocolo (cada `tool_result`
    debe seguir a su `tool_use`).
    """
    turns: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "user" and isinstance(content, str):
            turns.append({"role": "user", "content": content})
        elif role == "assistant":
            if isinstance(content, str):
                turns.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                texts = [block.get("text") for block in content if block.get("type") == "text"]
                if texts:
                    turns.append({"role": "assistant", "content": " ".join(texts)})
    return turns


def _outcome(
    escalation_reason: EscalationReason | None, booking_created: bool
) -> ConversationOutcome:
    """Outcome de la conversación (§7.7), con precedencia escalación > reserva."""
    if escalation_reason == EscalationReason.COMPLAINT:
        return ConversationOutcome.COMPLAINT
    if escalation_reason is not None:
        return ConversationOutcome.ESCALATED
    if booking_created:
        return ConversationOutcome.RESERVATION_CREATED
    return ConversationOutcome.QUERY


async def _load_customer(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> Customer | None:
    """Carga el cliente si existe y pertenece a la tenant (nunca cruzar datos)."""
    if customer_id is None:
        return None
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.restaurant_id != restaurant_id:
        return None
    return customer


async def run_conversation(
    session: AsyncSession,
    *,
    llm: LLMClient,
    restaurant: Restaurant,
    source_channel: SourceChannel,
    incoming_message: str,
    customer_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    prior_transcript: str | None = None,
    max_iterations: int = 5,
) -> ConversationResult:
    """Ejecuta una iteración de la conversación y la persiste.

    Crea la `Conversation` al inicio (para que la tool `escalate` tenga el
    `conversation_id`), hace `flush` (nunca `commit`), y la finaliza con el
    transcript de texto y el outcome. Un fallo del LLM produce un mensaje de
    respaldo y una escalación `technical_failure` (§9.11). Las excepciones de
    las tools (bug de programación) se propagan: el mapeo a mensaje no es de aquí.
    """
    turn = await _begin_turn(
        session,
        restaurant=restaurant,
        source_channel=source_channel,
        incoming_message=incoming_message,
        customer_id=customer_id,
        reservation_id=reservation_id,
        prior_transcript=prior_transcript,
    )
    state = _LoopState()

    for _ in range(max_iterations):
        try:
            response = await llm.generate(
                system=turn.system_prompt, messages=turn.messages, tools=tool_schemas()
            )
        except Exception:
            # Fallo técnico (§9.11): mensaje de respaldo + escalación, sin reintentar.
            return await _technical_failure(session, turn=turn, state=state)

        if not response.tool_calls:
            state.final_text = response.text or FALLBACK_TEXT
            break

        await _run_tool_round(turn=turn, response=response, state=state)
    else:
        # max_iterations agotado sin texto final: mensaje neutro, sin escalar.
        state.final_text = state.final_text or FALLBACK_TEXT

    return await _finalize(session, turn=turn, state=state)


async def run_conversation_stream(
    session: AsyncSession,
    *,
    llm: LLMClient,
    restaurant: Restaurant,
    source_channel: SourceChannel,
    incoming_message: str,
    customer_id: uuid.UUID | None = None,
    reservation_id: uuid.UUID | None = None,
    prior_transcript: str | None = None,
    max_iterations: int = 5,
) -> AsyncGenerator[tuple[str | None, ConversationResult | None], None]:
    """Mismo bucle que `run_conversation`, emitiendo el texto en deltas.

    Produce `(delta, None)` por cada fragmento de texto que va saliendo y
    termina con `(None, ConversationResult)`. Lo usa el canal de voz, que tiene
    que empezar a hablar antes de tener la respuesta completa.

    Los deltas de una ronda con tools (el típico "déjame comprobarlo") también
    se emiten: en voz es buena señal de actividad. Quien escucha el stream debe
    hablar solo los deltas y usar `result.text` para el transcript, nunca ambos.
    """
    turn = await _begin_turn(
        session,
        restaurant=restaurant,
        source_channel=source_channel,
        incoming_message=incoming_message,
        customer_id=customer_id,
        reservation_id=reservation_id,
        prior_transcript=prior_transcript,
    )
    state = _LoopState()

    for _ in range(max_iterations):
        try:
            response: LLMResponse | None = None
            async for chunk in llm.generate_stream(
                system=turn.system_prompt, messages=turn.messages, tools=tool_schemas()
            ):
                if chunk.text:
                    yield chunk.text, None
                if chunk.response is not None:
                    response = chunk.response
            if response is None:
                raise RuntimeError("generate_stream no devolvió una respuesta final")
        except Exception:
            yield None, await _technical_failure(session, turn=turn, state=state)
            return

        if not response.tool_calls:
            state.final_text = response.text or FALLBACK_TEXT
            break

        await _run_tool_round(turn=turn, response=response, state=state)
    else:
        state.final_text = state.final_text or FALLBACK_TEXT

    yield None, await _finalize(session, turn=turn, state=state)


@dataclass
class _Turn:
    """Estado de una iteración: contexto de tools, conversación y histórico."""

    ctx: ToolContext
    conversation: Conversation
    system_prompt: str
    messages: list[dict]


@dataclass
class _LoopState:
    """Señales que van dejando las tools y el LLM durante el bucle."""

    escalation_reason: EscalationReason | None = None
    escalation_id: uuid.UUID | None = None
    booking_created: bool = False
    final_text: str | None = None
    tool_calls_made: int = 0


async def _begin_turn(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    source_channel: SourceChannel,
    incoming_message: str,
    customer_id: uuid.UUID | None,
    reservation_id: uuid.UUID | None,
    prior_transcript: str | None,
) -> _Turn:
    """Prepara cliente (siempre de la misma tenant), conversación y mensajes."""
    customer = await _load_customer(session, restaurant_id=restaurant.id, customer_id=customer_id)
    # Cliente de otra tenant se trata como desconocido (no se arrastra su id).
    effective_customer_id = customer.id if customer is not None else None

    conversation = await create_conversation(
        session,
        restaurant_id=restaurant.id,
        customer_id=effective_customer_id,
        channel=ConversationChannel(source_channel.value),
    )
    ctx = ToolContext(
        session=session,
        restaurant_id=restaurant.id,
        source_channel=source_channel,
        customer_id=effective_customer_id,
        reservation_id=reservation_id,
        conversation_id=conversation.id,
    )
    return _Turn(
        ctx=ctx,
        conversation=conversation,
        system_prompt=build_system_prompt(
            restaurant=restaurant, customer=customer, source_channel=source_channel
        ),
        messages=[
            *transcript_from_json(prior_transcript),
            {"role": "user", "content": incoming_message},
        ],
    )


async def _run_tool_round(*, turn: _Turn, response: LLMResponse, state: _LoopState) -> None:
    """Ejecuta las tools pedidas y añade el intercambio assistant/tool_result."""
    assistant_content: list[dict] = []
    if response.text:
        assistant_content.append({"type": "text", "text": response.text})
    for call in response.tool_calls:
        assistant_content.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
        )
    turn.messages.append({"role": "assistant", "content": assistant_content})

    results: list[dict] = []
    for call in response.tool_calls:
        tool = tool_by_name(call.name)
        if tool is None:
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": f"tool desconocida: {call.name}",
                    "is_error": True,
                }
            )
            continue
        result = await tool.func(turn.ctx, call.input)
        state.tool_calls_made += 1
        results.append(
            {"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result)}
        )
        _register_tool_effect(call, result, state)
    turn.messages.append({"role": "user", "content": results})


def _register_tool_effect(call: ToolCall, result: dict, state: _LoopState) -> None:
    """Traduce el resultado de una tool a las señales del outcome."""
    if not result.get("ok"):
        return
    if result.get("needs_escalation"):
        reason = result.get("escalation_reason") or "large_group"
        state.escalation_reason = EscalationReason(reason)
    if call.name == "create_booking":
        state.booking_created = True
    # La tool escalate ya crea la fila Escalation: aquí solo se registra.
    if call.name == "escalate":
        state.escalation_reason = EscalationReason(result["escalation"]["reason"])
        state.escalation_id = uuid.UUID(result["escalation"]["id"])


async def _technical_failure(
    session: AsyncSession, *, turn: _Turn, state: _LoopState
) -> ConversationResult:
    """Cierre por fallo del LLM (§9.11): mensaje de respaldo + escalación."""
    escalation = await create_escalation(
        session,
        restaurant_id=turn.ctx.restaurant_id,
        conversation_id=turn.conversation.id,
        reason=EscalationReason.TECHNICAL_FAILURE,
    )
    transcript = transcript_to_json(
        [
            *_text_turns(turn.messages),
            {"role": "assistant", "content": TECHNICAL_FAILURE_TEXT},
        ]
    )
    await finalize_conversation(
        session,
        conversation=turn.conversation,
        transcript=transcript,
        outcome=ConversationOutcome.ESCALATED,
    )
    return ConversationResult(
        text=TECHNICAL_FAILURE_TEXT,
        outcome=ConversationOutcome.ESCALATED,
        conversation_id=turn.conversation.id,
        escalation_id=escalation.id,
        transcript=transcript,
        tool_calls=state.tool_calls_made,
    )


async def _finalize(session: AsyncSession, *, turn: _Turn, state: _LoopState) -> ConversationResult:
    """Persiste el transcript y el outcome, y crea la escalación que falte."""
    final_text = state.final_text or FALLBACK_TEXT
    transcript_turns = _text_turns(turn.messages)
    transcript_turns.append({"role": "assistant", "content": final_text})
    transcript = transcript_to_json(transcript_turns)

    escalation_id = state.escalation_id
    # La fila ya la creó la tool escalate; solo se crea aquí cuando la señal
    # viene de otra tool (p. ej. needs_escalation de create_booking).
    if state.escalation_reason is not None and escalation_id is None:
        escalation = await create_escalation(
            session,
            restaurant_id=turn.ctx.restaurant_id,
            conversation_id=turn.conversation.id,
            reason=state.escalation_reason,
        )
        escalation_id = escalation.id

    outcome = _outcome(state.escalation_reason, state.booking_created)
    await finalize_conversation(
        session, conversation=turn.conversation, transcript=transcript, outcome=outcome
    )
    return ConversationResult(
        text=final_text,
        outcome=outcome,
        conversation_id=turn.conversation.id,
        escalation_id=escalation_id,
        transcript=transcript,
        tool_calls=state.tool_calls_made,
    )
