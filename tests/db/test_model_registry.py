"""Verificacion global del registro de tablas en Base.metadata."""

import app.db.models  # noqa: F401
from app.db.base import Base

# Tablas de la seccion 7 que el backend posee y modela ahora.
EXPECTED_TABLES = {
    "restaurants",
    "tables",
    "shifts",
    "customers",
    "reservations",
    "reminders",
    "conversations",
    "escalations",
}

# Tablas del spec que quedan fuera de alcance (diferidas / no se modelan aqui).
DEFERRED_TABLES = {"owner_users", "menu_items", "preorders"}


def test_all_owned_section7_tables_registered() -> None:
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def test_deferred_tables_not_registered() -> None:
    assert not (DEFERRED_TABLES & set(Base.metadata.tables))
