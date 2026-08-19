# CLAUDE.md

Guía de contexto para trabajar en este repositorio con Claude Code.

## Objetivo del producto

SaaS multi-tenant de recepción por IA para restaurantes: un agente autónomo que
atiende **reservas y consultas frecuentes por WhatsApp y teléfono** 24/7, sin
depender de plataformas externas de reservas (TheFork, OpenTable) ni de sus
comisiones. Cliente piloto: *Er Pichi de Cai* (Alhaurín de la Torre).

La especificación funcional y técnica completa vive en
[`recepcionista-ia-whatsapp-telefono.md`](recepcionista-ia-whatsapp-telefono.md).
Es la fuente de verdad para modelo de datos, lógica de negocio y flujos de
conversación.

## Alcance de este repo

Este repo es **solo el backend** (FastAPI). El panel de administración
(Laravel + Livewire, Sanctum + Spatie Permissions) vive en **otro repositorio**
y se comunicará por HTTP interno con JWT compartido, sobre la misma PostgreSQL.

## Arquitectura: monolito modular (vertical slices)

Cada módulo de dominio es autocontenido y agrupa lo que le pertenece
(`models.py`, `schemas.py`, `service.py`, `router.py`):

```
app/modules/reservations/   models.py · schemas.py · service.py · router.py
app/modules/availability/   ...
app/modules/customers/      ...
app/modules/reminders/      ...
app/modules/faqs/           ...
app/agent/                  orquestador del agente LLM + tools (tool-calling)
app/db/                     sesión de base de datos (SQLAlchemy)
tests/                      espejo de la estructura anterior
```

## Mapeo de tablas a módulos

Correspondencia de las tablas de la sección 7 del spec con el código:

| Tabla (spec) | Dónde vive | Notas |
|---|---|---|
| `restaurants` | `app/core/` | Config de tenant, no dominio de negocio |
| `tables`, `shifts` | `app/modules/availability/` | |
| `customers` | `app/modules/customers/` | |
| `reservations` | `app/modules/reservations/` | FKs cruzadas a `table_id` y `customer_id` son normales entre módulos |
| `reminders` | `app/modules/reminders/` | |
| `conversations`, `escalations` | `app/agent/` | Metadatos de la conversación con el LLM, no dominio del restaurante |
| `faqs` | — (sin modelo propio) | RAG sobre datos de `restaurants`; la sección 7 no define tabla `faqs` |
| `owner_users` | — (NO se modela aquí) | Autenticación del panel, gestionada por Laravel/Eloquent en el otro repositorio |
| `menu_items`, `preorders` | — (diferido) | Módulo opcional de precomanda, fuera de alcance hasta abordarlo explícitamente |

## Stack

| Componente | Elección |
|---|---|
| Backend / agente | FastAPI (Python) |
| Base de datos | PostgreSQL (SQLAlchemy) |
| Caché / estado de conversación | Redis |
| LLM | Claude Haiku 4.5 vía tool-calling |
| WhatsApp | WhatsApp Business API vía 360dialog (webhook) |
| Voz | Twilio (telefonía / desvío de llamadas) + ElevenLabs (STT/TTS) |
| Recordatorios | Worker programado (por decidir: APScheduler / Celery) |

## Convenciones

- **Async en todo el path de request**: `async def` en endpoints, SQLAlchemy
  async, httpx async. Sin bloqueos en el path de request.
- **Tipado estricto con Pydantic**: cada módulo define sus propios schemas
  (ej. `app/modules/reservations/schemas.py`). Los modelos ORM viven en el
  `models.py` de su módulo.
- **SQLAlchemy 2.0** con declaración `Mapped[]`.
- **Tests con pytest** en `tests/` (`pytest-asyncio`, fixtures de DB de test y
  cliente ASGI). `tests/` espeja la estructura de `app/`. Todo lo que se toque
  debe tener test.
- **Multi-tenant por `restaurant_id`**: toda consulta filtra por tenant; nunca
  cruzar datos entre restaurantes.
- **Lógica de negocio pura dentro de cada módulo** (sin dependencia HTTP):
  por ejemplo `app/modules/reservations/service.py` con `create_reservation`,
  `modify`, `cancel`, o `app/modules/availability/service.py`. Reutilizable
  por WhatsApp, voz y panel.
- **Tools del LLM**: cada módulo expone su propio `tools.py` (junto a
  `models.py`, `schemas.py`, `service.py`, `router.py`), con funciones finas
  que delegan en su `service.py`. Si un módulo se extrae en el futuro, sus
  tools se van con él.
- **`app/agent/` contiene SOLO el orquestador**: cliente de Claude, bucle de
  conversación, memoria de contexto, y el punto que **agrega las tools de
  todos los módulos** para pasárselas al LLM (tool-calling).
- **Configuración por entorno en `app/core/`** (settings, seguridad, conexiones
  a servicios). Secretos solo en `.env` (no versionado).

## Entorno local (Windows + Laragon)

- Sistema: **Windows 10/11**. Desarrollo con **Laragon**: PostgreSQL se gestiona
  como servicio local de Laragon.
- **Redis NO lo gestiona Laragon**: se arranca manualmente y de forma
  independiente por el desarrollador (p. ej. `redis-server` desde su instalación).
- Python disponible vía Laragon; usar `.venv/` propio dentro del repo.
- Shell de trabajo: **Git Bash**.
- Base local de desarrollo: crear/gestionar con **psql / pgAdmin**
  (phpMyAdmin es solo para MySQL).

## Estado / roadmap

Fase actual: scaffolding (estructura + documentación). Siguientes pasos según el
roadmap del spec:

1. Modelos SQLAlchemy (tablas de la sección 7)
2. Motor de reservas (servicios puros)
3. Cliente LLM (Claude Haiku 4.5)
4. Tools para tool-calling
5. Orquestador de conversación
6. Webhook de WhatsApp (360dialog)
7. Canal de voz (Twilio + ElevenLabs)
8. Worker de recordatorios
