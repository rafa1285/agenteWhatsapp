"""Dependencias FastAPI compartidas: autenticación, tenant, cliente LLM, gateway WhatsApp."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.client import LLMClient
from app.channels.whatsapp.gateway import WhatsAppGateway
from app.core.auth import (
    JWTExpiredError,
    JWTInvalidClaimsError,
    JWTInvalidSignatureError,
    JWTValidationError,
    validate_token,
)
from app.core.models import Restaurant
from app.db.session import get_db_session


async def get_current_restaurant(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Restaurant:
    """
    Extrae y valida JWT del header `Authorization: Bearer <token>`,
    resuelve el `Restaurant` por `restaurant_id` del token,
    y verifica que esté activo.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header Authorization: Bearer <token> requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = validate_token(token)
    except JWTExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except (JWTInvalidSignatureError, JWTInvalidClaimsError, JWTValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    restaurant = await session.get(Restaurant, payload.restaurant_id)
    if not restaurant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Restaurante {payload.restaurant_id} no encontrado",
        )
    if not restaurant.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restaurante inactivo",
        )

    return restaurant


# Re-exportar dependencias de canales para routers
async def get_llm_client() -> LLMClient:
    """Cliente LLM (inyectable, overrideable en tests)."""
    from app.agent.client import ClaudeClient
    return ClaudeClient()


async def get_whatsapp_gateway() -> WhatsAppGateway:
    """Gateway WhatsApp (inyectable, overrideable en tests)."""
    from app.channels.whatsapp.gateway import Dialog360Client
    return Dialog360Client()
