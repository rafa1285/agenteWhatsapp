"""Tests del modelo `Restaurant` (capa core / tenant)."""

import app.db.models  # noqa: F401
from app.core.models import Restaurant
from sqlalchemy import Boolean, Integer, String, Time
from sqlalchemy.dialects.postgresql import JSONB, UUID


def test_restaurant_table_registered() -> None:
    assert Restaurant.__tablename__ == "restaurants"
    assert "restaurants" in Restaurant.metadata.tables


def test_restaurant_uuid_primary_key() -> None:
    col = Restaurant.__table__.c["id"]
    assert isinstance(col.type, UUID)
    assert col.primary_key is True


def test_restaurant_required_config_columns() -> None:
    table = Restaurant.__table__
    for name, sqltype in {
        "name": String,
        "public_phone": String,
        "whatsapp_number_id": String,
        "voice_number": String,
        "timezone": String,
    }.items():
        assert isinstance(table.c[name].type, sqltype)
        assert table.c[name].nullable is False


def test_restaurant_optional_columns() -> None:
    table = Restaurant.__table__
    for name in ("opening_time", "closing_time", "confirmation_deadline", "prompt_tone"):
        assert table.c[name].nullable is True


def test_restaurant_time_columns() -> None:
    table = Restaurant.__table__
    for name in ("opening_time", "closing_time", "confirmation_deadline"):
        assert isinstance(table.c[name].type, Time)


def test_restaurant_boolean_and_threshold_columns() -> None:
    table = Restaurant.__table__
    for name in ("active", "live_transfer_enabled", "preorder_enabled", "auto_confirm_enabled"):
        assert isinstance(table.c[name].type, Boolean)
        assert table.c[name].nullable is False
    for name in ("no_show_threshold", "large_group_threshold"):
        assert isinstance(table.c[name].type, Integer)


def test_restaurant_supported_languages_is_jsonb() -> None:
    col = Restaurant.__table__.c["supported_languages"]
    assert isinstance(col.type, JSONB)
    assert col.nullable is False
