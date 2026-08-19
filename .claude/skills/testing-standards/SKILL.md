---
name: testing-standards
description: Se activa al escribir o revisar tests, y justo después de implementar cualquier función en un service.py o cualquier endpoint en un router.py. Úsala para saber qué tests crear, con qué fixtures y qué cobertura se espera antes de dar un cambio por terminado.
---

# Estándares de testing

## Base

- **pytest** + **pytest-asyncio** (`asyncio_mode = "auto"` en `pyproject.toml`:
  los tests async no necesitan `@pytest.mark.asyncio`).
- `tests/` **espeja la estructura de `app/`**:
  `tests/modules/<modulo>/test_*.py`, `tests/core/`, `tests/agent/`, `tests/db/`.
- Regla del repo: **"todo lo que se toque debe tener test"**. Un cambio no está
  terminado hasta que sus tests pasan.

## Qué probar

- **Aislamiento multi-tenant es obligatorio**: al menos un test de que una
  reserva/cliente de un restaurante no es visible ni modificable desde otro
  (p. ej. fetch por `id` + `restaurant_id` de otra tenant → `NotFound`).
- **Lógica de negocio de `service.py`**: estados y transiciones del ciclo de
  vida, decisiones de estado inicial según riesgo/config, idempotencia sobre
  estados terminales, transiciones ilegales → error de dominio.
- **TDD recomendado para `service.py`** (motor de reservas): escribir primero
  el test que define el comportamiento esperado.
- Los tests de metadata (sin BD) verifican columnas, enums (valores `.value` y
  `CHECK` de BD), índices y constraints.

## Fixtures y base de datos de test

- Existe una BD propia **`agente_whatsapp_test`** en el mismo servidor
  PostgreSQL de desarrollo, creada a demanda. El motor de tests usa
  **`NullPool`** (obligatorio: evita que una conexión reaparecida cruce entre
  los event loops de pytest-asyncio → "Event loop is closed").
- `tests/conftest.py` expone:
  - `test_engine` (sync, session-scoped): crea la BD si falta, `drop_all` +
    `create_all` desde `Base.metadata`.
  - `db_session` (async, function-scoped): **trunca todas las tablas por test**
    (`TRUNCATE ... RESTART IDENTITY CASCADE`) y da una `AsyncSession` que nunca
    commitea (los servicios solo hacen `flush`).
  - Factories async: `restaurant_factory`, `table_factory`, `shift_factory`,
    `customer_factory`, `reservation_factory`. Los valores por defecto se fijan
    explícitamente (no depender de `server_default`: no se cargan en la
    instancia tras el `flush`).
- Los tests de servicio piden `db_session` y usan las factories; los tests de
  metadata no piden `db_session` y siguen sin tocar base de datos.
- Cuando existan routers: cliente **ASGI async** para probar endpoints.

## Cobertura

- Objetivo orientativo: **80% en `service.py`**, sin mínimo estricto en
  routers/schemas.

## Verificación antes de terminar

- `ruff check app tests` y `ruff format .` limpios (line-length 100).
- `pytest` completo verde (tests de servicio contra `agente_whatsapp_test` +
  tests de metadata sin BD).
- Si un test falla con "Event loop is closed": la causa es una conexión pooled
  reutilizada entre loops → el fix es `NullPool`, no un event loop custom.
