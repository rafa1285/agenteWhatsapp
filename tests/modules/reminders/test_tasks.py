"""Tests del wiring de Celery (sin broker: el import no conecta a Redis)."""

import app.modules.reminders.tasks  # noqa: F401  # registra el task en celery_app
from app.celery import celery_app

TASK_NAME = "reminders.process_due"


def test_beat_schedule_targets_process_due() -> None:
    assert celery_app.conf.beat_schedule[TASK_NAME]["task"] == TASK_NAME


def test_process_due_task_is_registered() -> None:
    assert TASK_NAME in celery_app.tasks
