# Recepcionista IA para restaurantes — Backend (FastAPI)

Backend del **SaaS multi-tenant de recepción por IA** para restaurantes: un
agente autónomo que atiende reservas y consultas frecuentes por **WhatsApp** y
**teléfono**, 24/7, sin depender de plataformas externas de reservas
(TheFork, OpenTable) ni de sus comisiones.

> La especificación funcional y técnica completa está en
> [`recepcionista-ia-whatsapp-telefono.md`](recepcionista-ia-whatsapp-telefono.md).

## Stack

- **FastAPI** (Python) — orquestador de conversación + motor de reservas
- **PostgreSQL** — base de datos principal (multi-tenant)
- **Redis** — caché / estado de conversaciones activas
- **Claude Haiku 4.5** — LLM del agente, vía tool-calling
- **360dialog / Meta Cloud API** — WhatsApp Business API
- **Twilio** — canal de voz (desvío de llamadas + STT/TTS via TwiML)

## Qué NO incluye este repositorio

- **Panel de administración** (Laravel + Livewire, Sanctum + Spatie Permissions):
  vive en un **repositorio aparte**. Se comunicará con esta API por HTTP interno
  con JWT compartido y comparten la misma PostgreSQL.
- Automatización comercial interna (n8n) y proceso de onboarding de clientes.

## Estado

Backend implementado y funcional. Incluye:
- Modelos de la sección 7 del spec + extensiones para voz y webhooks.
- Motor de reservas, disponibilidad y gestión de clientes.
- Orquestador de agente LLM (Claude Haiku 4.5) con tool-calling.
- Integración de WhatsApp (Meta Cloud API / 360dialog) y Voz (Twilio).
- Worker de recordatorios programados con Celery + Redis.
- Autenticación JWT RS256 para comunicación con el panel.
- Suite de tests completa (unidades, servicios y canales).
Siguiente paso: Pruebas de integración E2E con el panel y despliegue piloto.

## Puesta en marcha (Windows + Laragon)

Requisitos: Python **≥ 3.11** (disponible vía Laragon) y Git Bash.

```bash
# 1. Crear el entorno virtual
python -m venv .venv

# 2. Activar el entorno (Git Bash)
source .venv/Scripts/activate

# 3. Instalar dependencias (incluye las de desarrollo)
pip install -e ".[dev]"

# 4. Configurar variables de entorno
cp .env.example .env   # y rellenar los valores

# 5. Comprobar lint y tests
ruff check .
pytest
```

> Nota: Redis NO lo gestiona Laragon; se arranca manualmente por el
> desarrollador (p. ej. `redis-server`). PostgreSQL sí lo gestiona Laragon.

El entrypoint de la aplicación (`uvicorn app.main:app`) se añadirá cuando
exista el primer código de la API.

## Base de datos

La conexión se configura con `DATABASE_URL` en `.env` (ver `.env.example`):

```dotenv
DATABASE_URL=postgresql+asyncpg://usuario:password@localhost:5432/agente_whatsapp
```

- La URL **debe** usar el driver `postgresql+asyncpg` (SQLAlchemy async). Para
  comprobarlo:
  ```
  .venv/Scripts/python.exe -c "from app.core.settings import settings; from sqlalchemy.engine import make_url; print(make_url(settings.DATABASE_URL).drivername)"
  ```
  Debe imprimir `postgresql+asyncpg`. Si la URL es inválida, el import de
  `app.db.session` falla con un `ValueError`.
- **UUID generados por PostgreSQL**: las claves primarias usan
  `gen_random_uuid()`, disponible en el core de PostgreSQL desde la **13** (sin
  extensión; Laragon trae 14.5+). El UUID se genera en la base de datos para
  que FastAPI y Laravel inserten igual sobre la misma BD.
- **Migraciones (Alembic)**: la primera migración (`crear_modelos_seccion_7`)
  ya está creada y aplicada sobre la BD de desarrollo. Tras tocar los modelos,
  regenerar y aplicar con:
  ```
  .venv/Scripts/alembic.exe revision --autogenerate -m "descripcion"
  .venv/Scripts/alembic.exe upgrade head
  ```
- **Enums**: se modelan como `VARCHAR` + `CHECK` (`native_enum=False`). La BD
  guarda los `.value` del `StrEnum` (p. ej. `indoor`, no `INDOOR`) gracias a
  `values_callable=enum_values`, y el `CHECK` se declara explícitamente en
  `__table_args__` con `enum_check(...)`. Esto es importante: los CHECK
  generados por `Enum(create_constraint=True)` no los puede comparar Alembic en
  autogenerate (pediría borrarlos), mientras que los explícitos sí.

## Estructura

```
app/               # aplicación FastAPI (monolito modular / vertical slices)
├── core/          # configuración, seguridad, conexiones
├── modules/       # módulos de dominio autocontenidos (models, schemas, service, router)
│   ├── reservations/
│   ├── availability/
│   ├── customers/
│   ├── reminders/
│   └── faqs/
├── agent/         # orquestador del agente LLM + tools (tool-calling)
└── db/            # sesión de base de datos (SQLAlchemy)
tests/             # tests (pytest), espejo de la estructura de app/
docs/              # documentación adicional
```
