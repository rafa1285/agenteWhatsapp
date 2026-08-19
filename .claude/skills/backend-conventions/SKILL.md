---
name: backend-conventions
description: Se activa al crear o editar cualquier archivo dentro de app/ (modelos SQLAlchemy, schemas Pydantic, servicios, routers, tools, configuración). Úsala siempre que añadas, modifiques o muevas código backend para que respete la arquitectura y las convenciones del repo.
---

# Convenciones de backend (FastAPI, monolito modular)

Repo de **solo backend** (FastAPI + PostgreSQL + Redis) de un SaaS multi-tenant
de recepción por IA para restaurantes. La fuente de verdad funcional y técnica
es `recepcionista-ia-whatsapp-telefono.md`. No toques el panel (Laravel, otro
repo).

## Arquitectura: monolito modular (vertical slices)

Cada módulo de dominio es autocontenido y agrupa lo que le pertenece:

```
app/modules/reservations/   models.py · schemas.py · service.py · router.py · tools.py
app/modules/availability/   ...
app/modules/customers/      ...
app/modules/reminders/      ...
app/modules/faqs/           ...
app/agent/                  SOLO el orquestador del LLM + metadatos de conversación
app/db/                     base declarativa, mixins, sesión (SQLAlchemy async)
app/core/                   settings, seguridad, excepciones, modelo `Restaurant`
```

- Las **tools del LLM** (`tools.py`) son funciones finas que **delegan en su
  `service.py`**; cada módulo expone las suyas. Si un módulo se extrae en el
  futuro, sus tools se van con él.
- **`app/agent/` no contiene lógica de negocio**: solo orquesta el bucle de
  conversación con Claude y **agrega** las tools de todos los módulos.

## Async en todo el path de request

- `async def` en endpoints, SQLAlchemy async (asyncpg), httpx async.
- Sin bloqueos en el path de request.

## Modelos y base de datos

- **Claves primarias**: `UUID` **generado por PostgreSQL**
  (`server_default=text("gen_random_uuid()")`, vía `UUIDPrimaryKeyMixin` en
  `app/db/base.py`). Nada de `uuid.uuid4()` en Python: el UUID se genera en la
  BD para que FastAPI y Laravel inserten igual sobre la misma PostgreSQL.
- **Enums**: `StrEnum` + `sa.Enum(..., native_enum=False, values_callable=enum_values)` →
  `VARCHAR` + `CHECK`. La BD guarda los `.value` (p. ej. `indoor`, no `INDOOR`).
  El `CHECK` se declara explícitamente en `__table_args__` con `enum_check(...)`
  (nunca `create_constraint=True`: Alembic no puede compararlo en autogenerate).
- **Nombres de columna en inglés**; el spec ya traducido es la fuente de verdad.
- **SQLAlchemy 2.0** con declaración `Mapped[...]`. `TimestampMixin` para
  `created_at`/`updated_at` (`DateTime(timezone=True)`).
- Los modelos se importan en `app/db/models.py` para que se registren en
  `Base.metadata` y Alembic los descubra. Después de tocar modelos, regenerar y
  aplicar la migración (`alembic revision --autogenerate` / `alembic upgrade head`).

## Multi-tenant

- **Toda consulta filtra por `restaurant_id`**; nunca cruzar datos entre
  restaurantes. El `restaurant_id` llega del contexto del tenant (auth JWT en
  routers, restaurante de la conversación en el agente).
- El aislamiento multi-tenant es también un control de **seguridad** (ver
  [[rgpd-security]]).

## Lógica de negocio

- Lógica pura en `service.py` de cada módulo, **sin dependencia HTTP**:
  reutilizable por WhatsApp, voz y panel.
- Los servicios hacen `flush` (nunca `commit` ni `rollback`); el caller
  (router, tool, orquestador, test) decide el límite de la transacción.
- `datetime.now(UTC)` solo para columnas tz-aware (`checked_in_at`,
  `customer.last_visit`).

## Schemas e I/O

- **Pydantic v2** para todo I/O. Cada módulo define sus propios schemas.
- Los schemas de entrada (`*Input`) son el contrato para routers y tools; el
  `restaurant_id` no forma parte de ellos.

## Configuración y secretos

- Configuración por entorno en `app/core/settings.py` (pydantic-settings).
- **Secretos solo vía `.env`** (no versionado). Nunca hardcodearlos ni
  commitearlos. Ver [[rgpd-security]].
