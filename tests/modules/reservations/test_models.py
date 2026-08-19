"""Tests del modelo `Reservation` y sus enums."""

import app.db.models  # noqa: F401
from app.modules.reservations.models import (
    AssignmentReason,
    Reservation,
    ReservationStatus,
    SourceChannel,
)
from sqlalchemy import Boolean, Date, DateTime, Integer, Text, Time
from sqlalchemy import Enum as SAEnum


def test_reservation_status_values_match_glossary() -> None:
    assert [s.value for s in ReservationStatus] == [
        "pending",
        "pending_confirmation",
        "confirmed",
        "modified",
        "cancelled",
        "completed",
        "no_show",
    ]


def test_source_channel_values_match_glossary() -> None:
    assert [c.value for c in SourceChannel] == ["whatsapp", "voice", "web"]


def test_assignment_reason_values_match_glossary() -> None:
    assert [r.value for r in AssignmentReason] == [
        "specific_request",
        "habitual_table",
        "standard_availability",
    ]


def test_reservation_registered_with_expected_columns() -> None:
    table = Reservation.__table__
    assert table.name == "reservations"
    assert isinstance(table.c["date"].type, Date)
    assert isinstance(table.c["time"].type, Time)
    assert isinstance(table.c["party_size"].type, Integer)
    assert isinstance(table.c["notes"].type, Text)
    assert isinstance(table.c["has_preorder"].type, Boolean)
    assert isinstance(table.c["checked_in_at"].type, DateTime)


def test_reservation_status_is_enum_with_default() -> None:
    col = Reservation.__table__.c["status"]
    assert isinstance(col.type, SAEnum)
    assert col.type.enum_class is ReservationStatus
    assert col.type.enums == [s.value for s in ReservationStatus]
    assert col.server_default is not None


def test_reservation_enum_db_values() -> None:
    """La BD guarda los `.value` del glosario, no los nombres del enum."""
    table = Reservation.__table__
    assert table.c["preferred_zone"].type.enums == ["indoor", "terrace", "bar"]
    assert table.c["source_channel"].type.enums == ["whatsapp", "voice", "web"]
    assert table.c["assignment_reason"].type.enums == [r.value for r in AssignmentReason]


def test_reservation_fks() -> None:
    refs = {fk.target_fullname for fk in Reservation.__table__.foreign_keys}
    assert {"restaurants.id", "customers.id", "tables.id"} <= refs


def test_reservation_indexes() -> None:
    names = {ix.name for ix in Reservation.__table__.indexes}
    assert "ix_reservations_restaurant_id_date" in names
    assert "ix_reservations_restaurant_id_status_date" in names
