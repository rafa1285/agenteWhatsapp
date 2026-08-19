"""Tests del modelo `Reminder` y sus enums."""

import app.db.models  # noqa: F401
from app.modules.reminders.models import Reminder, ReminderChannel, ReminderStatus, ReminderType
from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum


def test_reminder_type_values_match_glossary() -> None:
    assert [t.value for t in ReminderType] == [
        "24h_reminder",
        "mandatory_confirmation",
        "release_notice",
        "post_visit",
    ]


def test_reminder_status_values_match_glossary() -> None:
    assert [s.value for s in ReminderStatus] == ["pending", "sent", "failed", "cancelled"]


def test_reminder_channel_values_match_glossary() -> None:
    assert [c.value for c in ReminderChannel] == ["whatsapp", "sms"]


def test_reminder_registered_with_expected_columns() -> None:
    table = Reminder.__table__
    assert table.name == "reminders"
    assert isinstance(table.c["scheduled_send_at"].type, DateTime)
    assert table.c["scheduled_send_at"].nullable is False
    assert isinstance(table.c["sent_at"].type, DateTime)
    assert table.c["sent_at"].nullable is True


def test_reminder_status_is_enum_with_default() -> None:
    col = Reminder.__table__.c["status"]
    assert isinstance(col.type, SAEnum)
    assert col.type.enum_class is ReminderStatus
    # La BD guarda los `.value` del glosario (minúsculas), no los nombres del enum.
    assert col.type.enums == ["pending", "sent", "failed", "cancelled"]


def test_reminder_enum_db_values() -> None:
    table = Reminder.__table__
    assert table.c["type"].type.enums == [
        "24h_reminder",
        "mandatory_confirmation",
        "release_notice",
        "post_visit",
    ]
    assert table.c["channel"].type.enums == ["whatsapp", "sms"]


def test_reminder_reservation_fk() -> None:
    refs = {fk.target_fullname for fk in Reminder.__table__.foreign_keys}
    assert "reservations.id" in refs


def test_reminder_worker_index() -> None:
    names = {ix.name for ix in Reminder.__table__.indexes}
    assert "ix_reminders_status_scheduled_send_at" in names
