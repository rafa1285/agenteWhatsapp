"""Tests del envío por la API Cloud de Meta (sin red: MockTransport)."""

import json

import httpx
import pytest
import pytest_asyncio
from app.channels.whatsapp.gateway import (
    FakeWhatsAppGateway,
    MetaWhatsAppClient,
    WhatsAppSendError,
)


@pytest_asyncio.fixture
async def mock_http():
    """Fabrica de cliente httpx con MockTransport; captura la petición enviada."""

    http_clients: list[httpx.AsyncClient] = []

    def _make(status: int = 200, *, raise_error: type[httpx.HTTPError] | None = None):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if raise_error is not None:
                raise raise_error("boom")
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["headers"] = request.headers
            captured["json"] = json.loads(request.content)
            return httpx.Response(status, json={})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_clients.append(http)
        return http, captured

    yield _make

    for http in http_clients:
        await http.aclose()


async def test_send_text_builds_meta_cloud_request(mock_http) -> None:
    http, captured = mock_http()
    client = MetaWhatsAppClient(
        api_url="https://graph.facebook.com/v21.0",
        api_token="secret-key",
        phone_number_id="1080327585164011",
        http_client=http,
    )
    await client.send_text(to="34611111111", text="Hola, ¿qué tal?")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://graph.facebook.com/v21.0/1080327585164011/messages"
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    assert captured["json"] == {
        "messaging_product": "whatsapp",
        "to": "34611111111",
        "type": "text",
        "text": {"preview_url": False, "body": "Hola, ¿qué tal?"},
    }


async def test_send_text_non_2xx_raises(mock_http) -> None:
    http, _captured = mock_http(status=500)
    client = MetaWhatsAppClient(api_token="k", phone_number_id="1080327585164011", http_client=http)
    with pytest.raises(WhatsAppSendError):
        await client.send_text(to="34611111111", text="Hola")


async def test_send_text_network_error_raises(mock_http) -> None:
    http, _captured = mock_http(raise_error=httpx.ConnectError)
    client = MetaWhatsAppClient(api_token="k", phone_number_id="1080327585164011", http_client=http)
    with pytest.raises(WhatsAppSendError):
        await client.send_text(to="34611111111", text="Hola")


async def test_fake_gateway_captures_sends() -> None:
    gateway = FakeWhatsAppGateway()
    await gateway.send_text(to="34611111111", text="Hola")
    await gateway.send_text(to="34622222222", text="Adiós")
    assert gateway.sent == [
        {"to": "34611111111", "text": "Hola"},
        {"to": "34622222222", "text": "Adiós"},
    ]
