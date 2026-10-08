"""Punto de entrada de la API (FastAPI).

`create_app()` se usa tanto por uvicorn (`uvicorn app.main:app`) como por los
tests e2e (con `app.dependency_overrides`); `app = create_app()` es la instancia
global para producción. Sin lifespan: no hay recursos que abrir/cerrar en
arranque (los clientes LLM/WhatsApp son perezosos).
"""

from fastapi import FastAPI

from app.agent.router import router as agent_router
from app.channels.voice.router import router as voice_router
from app.channels.whatsapp.router import router as whatsapp_router

# Import all models so they register on Base.metadata before routers use them.
from app.db import models  # noqa: F401
from app.modules.availability.router import router as availability_router
from app.modules.customers.router import router as customers_router
from app.modules.faqs.router import router as faqs_router
from app.modules.reminders.router import router as reminders_router
from app.modules.reservations.router import router as reservations_router


def create_app() -> FastAPI:
    app = FastAPI(title="Recepción IA — Backend")

    # Webhooks (sin auth JWT: 360dialog / Twilio)
    app.include_router(whatsapp_router)
    app.include_router(voice_router)

    # API REST v1 (protegida con JWT panel → backend)
    app.include_router(reservations_router)
    app.include_router(availability_router)
    app.include_router(customers_router)
    app.include_router(reminders_router)
    app.include_router(faqs_router)
    app.include_router(agent_router)

    return app


app = create_app()
