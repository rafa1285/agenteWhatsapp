"""Envío de mensajes salientes por la API de WhatsApp Cloud de Meta.

`WhatsAppGateway` es el contrato (intercambiable en tests); `MetaWhatsAppClient`
lo implementa sobre httpx async contra `graph.facebook.com`; `FakeWhatsAppGateway`
captura los envíos sin hacer red. El header de autenticación es
`Authorization: Bearer` (estándar de Meta).
"""

from typing import Protocol

import httpx

from app.core.settings import settings


class WhatsAppGateway(Protocol):
    """Contrato del envío de WhatsApp (intercambiable, como `LLMClient`)."""

    async def send_text(self, *, to: str, text: str) -> None: ...


class WhatsAppSendError(RuntimeError):
    """El envío por la API de WhatsApp falló (no-2xx o error de red)."""


class MetaWhatsAppClient:
    """Cliente de la API de WhatsApp Cloud de Meta.

    El `http_client` es inyectable (httpx) para testear sin red vía
    `MockTransport`. Las credenciales se leen de settings (secretos en `.env`).
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_token: str | None = None,
        phone_number_id: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_url = api_url or settings.WHATSAPP_API_URL
        self._api_token = api_token or settings.WHATSAPP_API_TOKEN or ""
        self._phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID or ""
        self._http_client = http_client or httpx.AsyncClient(
            timeout=timeout if timeout is not None else settings.WHATSAPP_API_TIMEOUT
        )

    async def send_text(self, *, to: str, text: str) -> None:
        if not self._phone_number_id:
            raise WhatsAppSendError("WHATSAPP_PHONE_NUMBER_ID no configurado")

        url = f"{self._api_url}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        try:
            response = await self._http_client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"error de red al enviar a WhatsApp: {exc}") from exc
        if response.status_code >= 300:
            raise WhatsAppSendError(
                f"WhatsApp respondió {response.status_code} al enviar el mensaje"
            )


class FakeWhatsAppGateway:
    """Captura los envíos en `sent` para tests (no hace red)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_text(self, *, to: str, text: str) -> None:
        self.sent.append({"to": to, "text": text})
