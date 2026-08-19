"""Base declarativa y mixins comunes de la capa de datos (SQLAlchemy 2.0)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Naming convention estable para constraints e índices.
# Garantiza nombres consistentes entre migraciones (importante para Alembic).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa común de todos los modelos del proyecto."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """Valores de base de datos de un `StrEnum`: sus `.value`.

    Se pasa como `values_callable` de `sqlalchemy.Enum` para que la base de
    datos guarde los valores del glosario (p. ej. `indoor`, no `INDOOR`). Sin
    esto, SQLAlchemy persistiría el *nombre* del miembro.
    """

    return [member.value for member in enum_cls]


def enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    """CHECK de BD para una columna enum no nativa.

    `sa.Enum(..., create_constraint=True)` genera el constraint en el DDL, pero
    Alembic no puede compararlo en autogenerate y pediría borrarlo en cada
    migración. Un `CheckConstraint` explícito en `__table_args__` sí se
    compara, así que esquema y migraciones permanecen sincronizados. Los
    valores se derivan de los `.value` del enum (sin duplicarlos a mano).
    """

    values = ", ".join(f"'{value}'" for value in enum_values(enum_cls))
    return CheckConstraint(f"{column} IN ({values})", name=name)


class UUIDPrimaryKeyMixin:
    """Clave primaria UUID generada por PostgreSQL.

    Requiere PostgreSQL >= 13 (gen_random_uuid() está en el core desde la 13,
    sin extensión adicional; p. ej. Laragon trae 14.5+). El UUID se genera en
    la base de datos para que FastAPI y Laravel inserten filas por igual sobre
    la misma PostgreSQL.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Marcas de tiempo con zona horaria (nombres de columna en inglés)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
