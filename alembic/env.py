import asyncio
from logging.config import fileConfig

# Registra los modelos de dominio en Base.metadata para autogenerate.
import app.db.models  # noqa: F401
from alembic import context
from app.core.settings import settings
from app.db.base import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Objeto de configuración de Alembic (acceso a los valores de alembic.ini).
config = context.config

# Interpreta el fichero de configuración para el logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL de conexión la provee la configuración del proyecto (settings), no
# alembic.ini. Se escapa '%' para evitar interpolación de ConfigParser.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

# target_metadata: metadatos de Base para que `autogenerate` compare con la BD.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Ejecuta migraciones en modo offline (genera SQL sin conectar)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea un engine async (asyncpg) y ejecuta las migraciones online."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
