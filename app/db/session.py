"""Motor y sesión SQLAlchemy async (asyncpg). No bloquea el event loop."""

from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import settings


def _validate_database_url(database_url: str) -> None:
    """Rechaza URLs que no usen el driver asyncpg (SQLAlchemy async)."""
    drivername = make_url(database_url).drivername
    if drivername != "postgresql+asyncpg":
        raise ValueError(
            f"DATABASE_URL debe usar el driver 'postgresql+asyncpg' (recibido: '{drivername}')."
        )


_validate_database_url(settings.DATABASE_URL)

# create_async_engine es perezoso: no abre conexión al importar.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia FastAPI: una sesión por request, cerrada al terminar."""
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Cierra el pool de conexiones (al apagar la app o al final de los tests)."""
    await engine.dispose()
