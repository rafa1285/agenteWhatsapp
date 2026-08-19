"""Envío de mensajes salientes por la API de 360dialog.

`WhatsAppGateway` es el contrato (intercambiable en tests); `Dialog360Client`
lo implementa sobre httpx async contra `waba.360dialog.io`; `FakeWhatsAppGateway`
captura los envíos sin hacer red. El header de autenticación de 360dialog es
`D360-API-KEY` (su convención documentada); si el proveedor lo cambiara, es el
único punto a ajustar.
"""

from typing import Protocol

import httpx

from app.core.settings import settings


class WhatsAppGateway(Protocol):
    """Contrato del envío de WhatsApp (intercambiable, como `LLMClient`)."""

    async def send_text(self, *, to: str, text: str) -> None: ...


class WhatsAppSendError(RuntimeError):
    """El envío por la API de 360dialog falló (no-2xx o error de red)."""


class Dialog360Client:
    """Cliente de la API de 360dialog (proxy de la Cloud API de Meta).

    El `http_client` es inyectable (httpx) para testear sin red vía
    `MockTransport`. Las credenciales se leen de settings (secretos en `.env`).
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_url = api_url or settings.WHATSAPP_API_URL
        self._api_token = api_token or settings.WHATSAPP_API_TOKEN or ""
        self._http_client = http_client or httpx.AsyncClient(
            timeout=timeout if timeout is not None else settings.WHATSAPP_API_TIMEOUT
        )

    async def send_text(self, *, to: str, text: str) -> None:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        try:
            response = await self._http_client.post(
                self._api_url,
                headers={"D360-API-KEY": self._api_token},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"error de red al enviar a 360dialog: {exc}") from exc
        if response.status_code >= 300:
            raise WhatsAppSendError(
                f"360dialog respondió {response.status_code} al enviar el mensaje"
            )


class FakeWhatsAppGateway:
    """Captura los envíos en `sent` para tests (no hace red)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_text(self, *, to: str, text: str) -> None:
        self.sent.append({"to": to, "text": text})
