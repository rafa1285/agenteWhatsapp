"""Dependencias FastAPI del canal de voz.

La voz reutiliza los clientes LLM y WhatsApp del canal de WhatsApp (mismos
objetos de función): los overrides de `tests/conftest.py` (`get_llm_client`,
`get_whatsapp_gateway`) cubren el canal de voz sin tocar nada aquí.
"""

from app.channels.whatsapp.dependencies import (  # noqa: F401
    get_llm_client,
    get_whatsapp_gateway,
)
