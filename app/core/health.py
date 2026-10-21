"""Endpoint de salud: comprueba las dependencias reales del backend con timeout
corto para que un corte de Postgres o Qdrant no deje la petición colgada."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.core.settings import settings
from app.core.vector_store import vector_store_service
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_CHECK_TIMEOUT_SECONDS = 2.0


class HealthResponse(BaseModel):
    """`status=degraded` si alguna dependencia no responde; `checks` detalla el fallo."""

    status: Literal["ok", "degraded"]
    checks: dict[str, str]


async def _check_postgres() -> str:
    async with async_session_factory() as session:
        await session.execute(text("SELECT 1"))
    return "ok"


async def _check_qdrant() -> str:
    if settings.QDRANT_PATH:
        return f"embebido ({settings.QDRANT_PATH})"
    await vector_store_service.client.get_collections()
    return "ok"


async def _run(name: str, check) -> tuple[str, str]:
    try:
        return name, await asyncio.wait_for(check, timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning("Health check %s falló: %s", name, e)
        return name, f"error: {e!s}"


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """De paso deja el estado de las dependencias, no solo que el proceso vive."""
    checks = dict(
        await asyncio.gather(_run("postgres", _check_postgres()), _run("qdrant", _check_qdrant()))
    )
    if any(value.startswith("error") for value in checks.values()):
        response.status_code = 503
        return HealthResponse(status="degraded", checks=checks)
    return HealthResponse(status="ok", checks=checks)
