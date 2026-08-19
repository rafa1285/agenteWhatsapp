"""Tests e2e del router del webhook de WhatsApp (cliente ASGI real).

Es la prueba end-to-end local de la Fase 5: el payload de 360dialog entra por
HTTP, el router resuelve tenant/cliente, el orquestador corre y la respuesta
sale por el gateway. Usa `asgi_client` (app real con dependencias overrideadas)
y `db_session` para sembrar y commitear datos que la sesión de la app (NullPool,
sesión distinta) pueda ver.
"""

from datetime import date as date_type

from app.agent.client import LLMResponse, ToolCall
from app.agent.models import Conversation
from app.agent.orchestrator import FALLBACK_TEXT
from app.modules.customers.models import Customer
from app.modules.reservations.models import Reservation
from sqlalchemy import func, select

SERVICE_DATE = date_type(2026, 9, 15)


def _payload(
    *, messages: list[dict] | None = None, field: str = "messages", number_id: str = "wa-100000"
) -> dict:
    change = {"field": field, "value": {"metadata": {"phone_number_id": number_id}}}
    if messages is not None:
        change["value"]["messages"] = messages
    return {"object": "whatsapp_business_account", "entry": [{"id": "acct-1", "changes": [change]}]}


def _text_message(
    *, mid: str = "wamid.1", body: str = "Hola", sender: str = "+34611111111"
) -> dict:
    return {
        "from": sender,
        "id": mid,
        "timestamp": "1720000000",
        "type": "text",
        "text": {"body": body},
    }


async def _count(session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return await session.scalar(stmt)


async def test_verify_valid_token_returns_challenge(asgi_client) -> None:
    client, _llm, _gateway = asgi_client
    response = await client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "cambia-me",
            "hub.challenge": "123456",
        },
    )
    assert response.status_code == 200
    assert response.text == "123456"


async def test_verify_invalid_token_returns_403(asgi_client) -> None:
    client, _llm, _gateway = asgi_client
    response = await client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-equivocado",
            "hub.challenge": "123456",
        },
    )
    assert response.status_code == 403


async def test_verify_missing_params_returns_403(asgi_client) -> None:
    client, _llm, _gateway = asgi_client
    response = await client.get("/api/whatsapp/webhook")
    assert response.status_code == 403


async def test_e2e_happy_path_replies(asgi_client, db_session, restaurant_factory) -> None:
    restaurant = await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    await db_session.commit()  # la sesión de la app debe ver el restaurante
    restaurant_id = restaurant.id
    client, llm, gateway = asgi_client

    response = await client.post(
        "/api/whatsapp/webhook",
        json=_payload(messages=[_text_message(mid="wamid.1", body="Hola")]),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert gateway.sent == [{"to": "+34611111111", "text": FALLBACK_TEXT}]
    assert len(llm.calls) == 1
    assert await _count(db_session, Customer, restaurant_id=restaurant_id) == 1
    assert await _count(db_session, Conversation, restaurant_id=restaurant_id) == 1


async def test_e2e_booking_is_persisted(asgi_client, db_session, availability_setup) -> None:
    restaurant, _tables = await availability_setup()
    await db_session.commit()
    restaurant_id = restaurant.id
    client, llm, gateway = asgi_client

    llm.set_responses(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="toolu_01",
                        name="create_booking",
                        input={"date": SERVICE_DATE.isoformat(), "time": "14:00", "party_size": 2},
                    ),
                ),
            ),
            LLMResponse(text="Listo, tu reserva queda confirmada."),
        ]
    )

    response = await client.post(
        "/api/whatsapp/webhook",
        json=_payload(
            messages=[
                _text_message(
                    mid="wamid.1",
                    body="Quiero reservar mesa para dos el martes a las 14:00.",
                )
            ]
        ),
    )

    assert response.status_code == 200
    assert gateway.sent == [{"to": "+34611111111", "text": "Listo, tu reserva queda confirmada."}]
    reservation = await db_session.scalar(
        select(Reservation).where(Reservation.restaurant_id == restaurant_id)
    )
    assert reservation is not None
    assert reservation.party_size == 2
    customer = await db_session.scalar(
        select(Customer).where(Customer.restaurant_id == restaurant_id)
    )
    assert reservation.customer_id == customer.id


async def test_status_only_payload_is_ignored(asgi_client) -> None:
    client, llm, gateway = asgi_client
    response = await client.post("/api/whatsapp/webhook", json=_payload(field="statuses"))
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert llm.calls == []
    assert gateway.sent == []


async def test_unknown_number_is_ignored(asgi_client, db_session, restaurant_factory) -> None:
    await restaurant_factory(active=True, whatsapp_number_id="wa-100000")
    await db_session.commit()
    client, llm, gateway = asgi_client

    response = await client.post(
        "/api/whatsapp/webhook",
        json=_payload(messages=[_text_message(mid="wamid.1")], number_id="wa-desconocido"),
    )

    # El number_id no pertenece a ningún restaurante activo: se responde 200 y
    # no se procesa nada.
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert gateway.sent == []
    assert llm.calls == []
