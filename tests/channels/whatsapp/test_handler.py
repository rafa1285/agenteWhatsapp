"""Tests del handler del webhook de WhatsApp (procesado de mensaje entrante).

Llaman a `process_whatsapp_message` directamente (sin HTTP) con la sesión de
tests, `FakeLLMClient` y `FakeWhatsAppGateway`. El handler hace `commit`: cada
test arranca con la BD vacía (fixture `db_session`).
"""

from app.agent.client import FakeLLMClient
from app.agent.models import Conversation, ConversationChannel
from app.agent.orchestrator import FALLBACK_TEXT
from app.channels.whatsapp.gateway import FakeWhatsAppGateway
from app.channels.whatsapp.handler import process_whatsapp_message
from app.channels.whatsapp.models import WebhookMessage
from app.channels.whatsapp.schemas import InboundMessage, TextContent
from app.modules.customers.models import Customer
from sqlalchemy import func, select


def _message(
    *, mid: str = "wamid.1", body: str = "Hola", sender: str = "+34611111111"
) -> InboundMessage:
    return InboundMessage(id=mid, from_=sender, type="text", text=TextContent(body=body))


async def _count(session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return await session.scalar(stmt)


async def test_unknown_number_is_skipped(db_session, restaurant_factory) -> None:
    restaurant = await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    result = await process_whatsapp_message(
        db_session,
        phone_number_id="wa-otro",
        message=_message(),
        llm=llm,
        gateway=gateway,
    )

    assert result is None
    assert llm.calls == []
    assert gateway.sent == []
    assert await _count(db_session, Conversation, restaurant_id=restaurant.id) == 0
    assert await _count(db_session, WebhookMessage, restaurant_id=restaurant.id) == 0


async def test_inactive_tenant_is_skipped(db_session, restaurant_factory) -> None:
    await restaurant_factory(active=False, whatsapp_number_id="wa-100000")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    result = await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(),
        llm=llm,
        gateway=gateway,
    )

    assert result is None
    assert llm.calls == []
    assert gateway.sent == []


async def test_message_without_text_is_skipped(db_session, restaurant_factory) -> None:
    await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    result = await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(body=""),
        llm=llm,
        gateway=gateway,
    )

    assert result is None
    assert llm.calls == []
    assert gateway.sent == []


async def test_happy_path_creates_customer_conversation_and_reply(
    db_session, restaurant_factory
) -> None:
    restaurant = await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    result = await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.1", body="Hola", sender="+34611111111"),
        llm=llm,
        gateway=gateway,
    )

    assert result == FALLBACK_TEXT
    assert gateway.sent == [{"to": "+34611111111", "text": FALLBACK_TEXT}]
    # El LLM recibe solo el mensaje entrante (sin transcript previo).
    assert [m["role"] for m in llm.calls[0]["messages"]] == ["user"]
    assert llm.calls[0]["messages"][0]["content"] == "Hola"
    # Cliente creado de cero y vinculado a la conversación.
    customer = await db_session.scalar(
        select(Customer).where(Customer.restaurant_id == restaurant.id)
    )
    assert customer is not None
    assert customer.phone == "34611111111"
    assert await _count(db_session, Conversation, restaurant_id=restaurant.id) == 1
    conversation = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant.id)
    )
    assert conversation.customer_id == customer.id
    assert conversation.channel == ConversationChannel.WHATSAPP
    assert await _count(db_session, WebhookMessage, restaurant_id=restaurant.id) == 1


async def test_duplicate_message_id_is_processed_once(db_session, restaurant_factory) -> None:
    restaurant = await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    # El id se captura antes del procesado: el rollback del duplicado expira los
    # objetos de la sesión y acceder a `restaurant.id` después haría un
    # lazy-load síncrono (MissingGreenlet).
    restaurant_id = restaurant.id
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    first = await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.dup", body="Hola"),
        llm=llm,
        gateway=gateway,
    )
    second = await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.dup", body="Hola de nuevo"),
        llm=llm,
        gateway=gateway,
    )

    assert first == FALLBACK_TEXT
    assert second is None
    assert len(gateway.sent) == 1
    assert len(llm.calls) == 1
    assert await _count(db_session, Conversation, restaurant_id=restaurant_id) == 1
    assert await _count(db_session, Customer, restaurant_id=restaurant_id) == 1
    assert await _count(db_session, WebhookMessage, restaurant_id=restaurant_id) == 1


async def test_second_message_retakes_prior_transcript(db_session, restaurant_factory) -> None:
    await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.1", body="Hola"),
        llm=llm,
        gateway=gateway,
    )
    await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.2", body="¿Hay mesa para dos?"),
        llm=llm,
        gateway=gateway,
    )

    assert len(llm.calls) == 2
    # El segundo turno retoma el transcript del primero como contexto previo.
    messages = llm.calls[1]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "Hola"
    assert messages[2]["content"] == "¿Hay mesa para dos?"


async def test_existing_customer_is_reused(
    db_session, restaurant_factory, customer_factory
) -> None:
    restaurant = await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    # El panel guarda el teléfono ya normalizado (solo dígitos, como
    # `normalize_phone`); el handler debe reencontrar a ese mismo cliente.
    existing = await customer_factory(restaurant.id, phone="34611111111", name="Ana")
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.1", body="Hola", sender="+34611111111"),
        llm=llm,
        gateway=gateway,
    )

    assert await _count(db_session, Customer, restaurant_id=restaurant.id) == 1
    conversation = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant.id)
    )
    assert conversation.customer_id == existing.id
    assert "Ana" in llm.calls[0]["system"]


async def test_payload_for_one_restaurant_does_not_touch_other(
    db_session, restaurant_factory
) -> None:
    restaurant_a = await restaurant_factory(
        active=True, whatsapp_number_id="wa-100000", name="Restaurante A"
    )
    restaurant_b = await restaurant_factory(
        active=True, whatsapp_number_id="wa-200000", name="Restaurante B"
    )
    llm = FakeLLMClient()
    gateway = FakeWhatsAppGateway()

    await process_whatsapp_message(
        db_session,
        phone_number_id="wa-100000",
        message=_message(mid="wamid.1", body="Hola", sender="+34611111111"),
        llm=llm,
        gateway=gateway,
    )

    assert await _count(db_session, Customer, restaurant_id=restaurant_a.id) == 1
    assert await _count(db_session, Customer, restaurant_id=restaurant_b.id) == 0
    assert await _count(db_session, Conversation, restaurant_id=restaurant_a.id) == 1
    assert await _count(db_session, Conversation, restaurant_id=restaurant_b.id) == 0
