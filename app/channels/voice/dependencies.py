"""Dependencias FastAPI del canal de voz.

La voz reutiliza los clientes LLM y WhatsApp del canal de WhatsApp (mismos
objetos de función): los overrides de `tests/conftest.py` (`get_llm_client`,
`get_whatsapp_gateway`) cubren el canal de voz sin tocar nada aquí.
"""

import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Request

from app.channels.whatsapp.dependencies import (  # noqa: F401
    get_llm_client,
    get_whatsapp_gateway,
)
from app.core.settings import settings

logger = logging.getLogger(__name__)


def validate_twilio_signature(request: Request, *, form_data: Mapping[str, Any]) -> bool:
    """Valida `X-Twilio-Signature` si hay token Twilio configurado.

    Cuando el token no está configurado, la validación está desactivada o el
    proceso corre en modo TESTING, el webhook acepta el request.
    """
    auth_token = (settings.TWILIO_AUTH_TOKEN or "").strip()
    if settings.TESTING or not settings.TWILIO_VALIDATE_SIGNATURE or not auth_token:
        return True

    header_value = request.headers.get("X-Twilio-Signature", "")
    if not header_value:
        logger.warning("Twilio webhook sin cabecera X-Twilio-Signature en %s", request.url.path)
        return False

    # Twilio firma la URL pública exacta del webhook. Usamos VOICE_BASE_URL
    # (túnel/dominio) + path para no depender del host interno visto por uvicorn.
    url = f"{settings.VOICE_BASE_URL.rstrip('/')}{request.url.path}"
    pairs: list[tuple[str, str]] = []
    for key, value in form_data.items():
        if isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((str(key), str(item)))
        else:
            pairs.append((str(key), str(value)))
    payload = "".join(f"{key}{value}" for key, value in sorted(pairs))
    digest = hmac.new(
        auth_token.encode("utf-8"),
        f"{url}{payload}".encode(),
        hashlib.sha1,
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, header_value)
