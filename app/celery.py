"""Aplicación Celery del worker de recordatorios (broker/beat en Redis).

Celery es solo el disparador periódico: el tick vive en el dominio
(`app/modules/reminders/service.py::process_due_reminders`) y el task
(`app/modules/reminders/tasks.py`) se limita a ejecutarlo. No conecta a Redis al
importar (lazy), así que este módulo es importable en tests sin broker levantado.

Arranque local (Windows): `celery -A app.celery_app worker --beat --pool=threads`
(`--pool=threads` porque el prefork por defecto no funciona en Windows).
"""

from app.core.settings import settings
from celery import Celery

celery_app = Celery("agente_whatsapp", include=["app.modules.reminders.tasks"])
celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    timezone="UTC",
    task_ignore_result=True,
    beat_schedule={
        "reminders.process_due": {
            "task": "reminders.process_due",
            "schedule": settings.REMINDER_TICK_INTERVAL_SECONDS,
        }
    },
)
