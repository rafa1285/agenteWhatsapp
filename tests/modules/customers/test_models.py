"""Tests del modelo `Customer`."""

import app.db.models  # noqa: F401
from app.modules.customers.models import Customer
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB


def test_customer_registered_with_expected_columns() -> None:
    table = Customer.__table__
    assert table.name == "customers"
    assert isinstance(table.c["phone"].type, String)
    assert table.c["phone"].nullable is False
    assert isinstance(table.c["name"].type, String)
    assert table.c["name"].nullable is True
    assert isinstance(table.c["allergies"].type, Text)
    assert isinstance(table.c["preferences"].type, Text)
    assert isinstance(table.c["visit_count"].type, Integer)
    assert isinstance(table.c["last_visit"].type, DateTime)
    assert isinstance(table.c["no_show_count"].type, Integer)
    assert isinstance(table.c["requires_prior_confirmation"].type, Boolean)
    assert isinstance(table.c["last_complaint_date"].type, Date)
    assert isinstance(table.c["estimated_average_ticket"].type, Numeric)
    assert isinstance(table.c["last_order"].type, JSONB)


def test_customer_phone_unique_per_restaurant() -> None:
    constraints = Customer.__table__.constraints
    names = {c.name for c in constraints if isinstance(c, UniqueConstraint)}
    assert "uq_customers_restaurant_id_phone" in names


def test_customer_fks() -> None:
    refs = {fk.target_fullname for fk in Customer.__table__.foreign_keys}
    assert "restaurants.id" in refs
    assert "tables.id" in refs
