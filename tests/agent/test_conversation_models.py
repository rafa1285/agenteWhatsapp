"""Tests de los modelos del agente (`Conversation`, `Escalation`)."""

import app.db.models  # noqa: F401
from app.agent.models import (
    Conversation,
    ConversationChannel,
    ConversationOutcome,
    Escalation,
    EscalationReason,
    EscalationStatus,
)
from sqlalchemy import DateTime, Text
from sqlalchemy import Enum as SAEnum


def test_conversation_channel_values() -> None:
    assert [c.value for c in ConversationChannel] == ["whatsapp", "voice"]


def test_conversation_outcome_values_match_glossary() -> None:
    assert [o.value for o in ConversationOutcome] == [
        "reservation_created",
        "query",
        "complaint",
        "escalated",
    ]


def test_conversation_registered_with_expected_columns() -> None:
    table = Conversation.__table__
    assert table.name == "conversations"
    assert isinstance(table.c["transcript"].type, Text)
    assert table.c["transcript"].nullable is False
    assert isinstance(table.c["date"].type, DateTime)
    assert table.c["outcome"].nullable is True


def test_conversation_fks() -> None:
    refs = {fk.target_fullname for fk in Conversation.__table__.foreign_keys}
    assert {"restaurants.id", "customers.id"} <= refs


def test_escalation_reason_contains_technical_failure() -> None:
    assert "technical_failure" in [r.value for r in EscalationReason]


def test_escalation_status_values() -> None:
    assert [s.value for s in EscalationStatus] == ["pending", "resolved"]


def test_escalation_registered_with_expected_columns() -> None:
    table = Escalation.__table__
    assert table.name == "escalations"
    assert isinstance(table.c["date"].type, DateTime)
    assert isinstance(table.c["reason"].type, SAEnum)


def test_agent_enum_db_values() -> None:
    """La BD guarda los `.value` del glosario, no los nombres del enum."""
    assert Conversation.__table__.c["channel"].type.enums == ["whatsapp", "voice"]
    assert Conversation.__table__.c["outcome"].type.enums == [
        "reservation_created",
        "query",
        "complaint",
        "escalated",
    ]
    assert Escalation.__table__.c["reason"].type.enums == [r.value for r in EscalationReason]
    assert Escalation.__table__.c["status"].type.enums == ["pending", "resolved"]


def test_escalation_fks() -> None:
    refs = {fk.target_fullname for fk in Escalation.__table__.foreign_keys}
    assert {"restaurants.id", "conversations.id"} <= refs
