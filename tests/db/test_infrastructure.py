"""Tests de la infraestructura común de base de datos.

No requieren una instancia de PostgreSQL en ejecución: solo importan y
revisan metadatos/sesiones sin abrir conexiones reales.
"""

import uuid
from typing import get_args, get_origin

import pytest
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------- Base


def test_base_is_importable() -> None:
    assert Base is not None


def test_metadata_has_naming_convention() -> None:
    metadata = Base.metadata
    for key in ("ix", "uq", "ck", "fk", "pk"):
        assert key in metadata.naming_convention


def test_naming_convention_templates_use_valid_tokens() -> None:
    templates = Base.metadata.naming_convention
    # Las plantillas usan formato Python %(token)s (p. ej. %(table_name)s).
    assert "%(table_name)s" in templates["pk"]
    assert "%(table_name)s" in templates["uq"]
    assert "%(column_0_label)s" in templates["ix"]
    assert "%(column_0_name)s" in templates["fk"]


# ------------------------------------------------------------------------- Mixins


class DemoModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Modelo de prueba que combina los mixins (solo para tests)."""

    __tablename__ = "demo_infra"


def test_uuid_primary_key_is_postgresql_uuid() -> None:
    col = DemoModel.__table__.c["id"]
    assert isinstance(col.type, UUID)
    assert col.primary_key is True
    assert col.nullable is False
    assert col.server_default is not None
    assert "gen_random_uuid" in str(col.server_default.arg)


def test_id_python_type_is_uuid() -> None:
    annotation = UUIDPrimaryKeyMixin.__annotations__["id"]
    assert get_origin(annotation).__name__ == "Mapped"
    assert get_args(annotation)[0] is uuid.UUID


def test_timestamp_columns_type_and_defaults() -> None:
    table = DemoModel.__table__
    for name in ("created_at", "updated_at"):
        col = table.c[name]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True
        assert col.nullable is False
        assert "now()" in str(col.server_default.arg)


def test_updated_at_has_onupdate() -> None:
    updated = DemoModel.__table__.c["updated_at"]
    assert updated.onupdate is not None
    # El func now() queda envuelto en ColumnElementColumnDefault (.arg).
    assert "now()" in str(updated.onupdate.arg)


# ------------------------------------------------------------------------ Sesión


def test_session_importable_without_db() -> None:
    from app.db.session import async_session_factory, engine, get_db_session

    assert engine is not None
    assert async_session_factory is not None
    assert callable(get_db_session)


def test_engine_uses_asyncpg_driver() -> None:
    from app.db.session import engine

    assert engine.url.drivername == "postgresql+asyncpg"


def test_validate_database_url_rejects_non_asyncpg() -> None:
    from app.db.session import _validate_database_url

    with pytest.raises(ValueError):
        _validate_database_url("postgresql://user:pass@localhost/db")


async def test_get_db_session_yields_async_session() -> None:
    from app.db.session import get_db_session

    async for session in get_db_session():
        assert isinstance(session, AsyncSession)
        break
