"""Dependencias FastAPI del canal WhatsApp (inyectables y overridables en tests).

Devuelven los clientes de producción (Claude + 360dialog) construidos con
settings; en los tests se sustituyen con `app.dependency_overrides` por
`FakeLLMClient` y `FakeWhatsAppGateway`.
"""

from app.agent.client import ClaudeClient
from app.channels.whatsapp.gateway import Dialog360Client


def get_llm_client() -> ClaudeClient:
    """Cliente LLM de producción (Claude Haiku 4.5); override en tests."""
    return ClaudeClient()


def get_whatsapp_gateway() -> Dialog360Client:
    """Gateway de 360dialog (httpx async); override en tests."""
    return Dialog360Client()
