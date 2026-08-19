"""Tests del parseo del payload entrante de WhatsApp (360dialog/Meta)."""

from app.channels.whatsapp.schemas import WebhookPayload


def _payload(*, messages: list[dict] | None = None, field: str = "messages") -> dict:
    """Construye un payload realista de la Cloud API (proxy 360dialog)."""
    change = {"field": field, "value": {"metadata": {"phone_number_id": "wa-100000"}}}
    if messages is not None:
        change["value"]["messages"] = messages
    return {"object": "whatsapp_business_account", "entry": [{"id": "acct-1", "changes": [change]}]}


def _text_message(
    *, mid: str = "wamid.ABC", body: str = "Hola", sender: str = "34611111111"
) -> dict:
    return {
        "from": sender,
        "id": mid,
        "timestamp": "1720000000",
        "type": "text",
        "text": {"body": body},
    }


def test_parses_text_message() -> None:
    payload = WebhookPayload.model_validate(_payload(messages=[_text_message()]))
    inbound = payload.inbound()
    assert inbound is not None
    phone_number_id, message = inbound
    assert phone_number_id == "wa-100000"
    assert message.id == "wamid.ABC"
    assert message.from_ == "34611111111"
    assert message.text is not None
    assert message.text.body == "Hola"


def test_status_only_payload_has_no_inbound() -> None:
    payload = WebhookPayload.model_validate(_payload(field="statuses"))
    assert payload.inbound() is None


def test_message_without_body_is_ignored() -> None:
    payload = WebhookPayload.model_validate(
        _payload(messages=[_text_message(body=""), _text_message(mid="wamid.2", body="Real")])
    )
    _phone, message = payload.inbound() or (None, None)
    assert message is not None
    assert message.id == "wamid.2"


def test_first_text_message_wins() -> None:
    payload = WebhookPayload.model_validate(
        _payload(messages=[_text_message(mid="wamid.1"), _text_message(mid="wamid.2")])
    )
    _phone, message = payload.inbound() or (None, None)
    assert message is not None
    assert message.id == "wamid.1"


def test_tolerant_to_missing_fields() -> None:
    payload = WebhookPayload.model_validate({})
    assert payload.inbound() is None
    assert payload.entry == []
