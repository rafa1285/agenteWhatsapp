"""Tasks de Celery del worker de recordatorios.

Wrapper síncrono sobre el tick async. El repo es 100% async (SQLAlchemy asyncpg);
en Windows cada task de Celery abre y cierra su propio event loop, así que el
task construye su propia sesión con un engine `NullPool` dedicado: un pool normal
reutilizaría conexiones entre loops ("Event loop is closed"). Bajo volumen (un
tick cada pocos minutos), el coste de abrir/cerrar conexión es irrelevante.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.celery import celery_app
from app.channels.whatsapp.gateway import MetaWhatsAppClient
from app.core.settings import settings
from app.modules.reminders.service import process_due_reminders


async def _process_due() -> int:
    """Tick async con su propia sesión (NullPool) y el gateway real."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await process_due_reminders(
                session, gateway=MetaWhatsAppClient(), now=datetime.now(UTC)
            )
    finally:
        await engine.dispose()


@celery_app.task(name="reminders.process_due")
def process_due_task() -> int:
    """Tick programado: procesa los recordatorios PENDING vencidos."""
    return asyncio.run(_process_due())
