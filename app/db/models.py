"""Punto unico de importacion de los modelos de dominio.

Todos los modelos se importan aqui para que se registren en `Base.metadata`
y Alembic (`autogenerate`) pueda descubrirlos. Cada modelo vive en el
`models.py` de su modulo (ver el mapeo de tablas a modulos en CLAUDE.md).

Quedan fuera (diferidos): `owner_users` (gestionado por Laravel), `menu_items`
y `preorders` (modulo opcional de precomanda, fuera de alcance hasta
abordarlo explicitamente).
"""

from app.agent.models import Conversation, Escalation  # noqa: F401
from app.channels.voice.models import VoiceCall  # noqa: F401
from app.channels.whatsapp.models import WebhookMessage  # noqa: F401
from app.core.models import Restaurant  # noqa: F401
from app.modules.availability.models import Shift, Table  # noqa: F401
from app.modules.customers.models import Customer  # noqa: F401
from app.modules.reminders.models import Reminder  # noqa: F401
from app.modules.reservations.models import Reservation  # noqa: F401
