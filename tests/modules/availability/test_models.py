"""Tests de los modelos de disponibilidad (`tables`, `shifts`)."""

import app.db.models  # noqa: F401
from app.modules.availability.models import Shift, Table, TableZone
from sqlalchemy import CheckConstraint, Date, Integer, Numeric, String, Time
from sqlalchemy import Enum as SAEnum


def test_table_zone_enum_values_match_glossary() -> None:
    assert [z.value for z in TableZone] == ["indoor", "terrace", "bar"]


def test_table_registered_with_expected_columns() -> None:
    table = Table.__table__
    assert table.name == "tables"
    assert isinstance(table.c["name"].type, String)
    assert isinstance(table.c["min_capacity"].type, Integer)
    assert isinstance(table.c["max_capacity"].type, Integer)
    assert isinstance(table.c["position_x"].type, Numeric)
    assert isinstance(table.c["position_y"].type, Numeric)


def test_table_zone_is_non_native_enum() -> None:
    col = Table.__table__.c["zone"]
    assert isinstance(col.type, SAEnum)
    assert col.type.enum_class is TableZone
    # La BD guarda los `.value` del glosario (minúsculas), no los nombres del enum.
    assert col.type.enums == ["indoor", "terrace", "bar"]


def test_table_zone_has_db_check_constraint() -> None:
    """El enum no nativo debe emitir un CHECK en BD (la comparte el panel Laravel)."""
    zone_checks = [
        c
        for c in Table.__table__.constraints
        if isinstance(c, CheckConstraint) and "zone" in str(c.sqltext)
    ]
    assert zone_checks, "falta CHECK constraint en BD para tables.zone"
    # Los valores del glosario quedan explícitos en el CHECK (en minúsculas).
    assert "indoor" in str(zone_checks[0].sqltext)
    assert "INDOOR" not in str(zone_checks[0].sqltext)


def test_table_restaurant_fk() -> None:
    refs = {fk.target_fullname for fk in Table.__table__.foreign_keys}
    assert "restaurants.id" in refs


def test_shift_registered_with_expected_columns() -> None:
    table = Shift.__table__
    assert table.name == "shifts"
    assert isinstance(table.c["weekday"].type, Integer)
    assert table.c["weekday"].nullable is True
    assert isinstance(table.c["special_date"].type, Date)
    assert isinstance(table.c["start_time"].type, Time)
    assert isinstance(table.c["end_time"].type, Time)
    assert isinstance(table.c["average_table_duration"].type, Integer)
    assert isinstance(table.c["max_capacity"].type, Integer)


def test_shift_restaurant_fk() -> None:
    refs = {fk.target_fullname for fk in Shift.__table__.foreign_keys}
    assert "restaurants.id" in refs
