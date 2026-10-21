# Recepcionista IA para restaurantes — Backend (FastAPI)

Backend del **SaaS multi-tenant de recepción por IA** para restaurantes: un
agente autónomo que atiende reservas y consultas frecuentes por **WhatsApp** y
**teléfono**, 24/7, sin depender de plataformas externas de reservas
(TheFork, OpenTable) ni de sus comisiones.

> La especificación funcional y técnica completa está en
> [`recepcionista-ia-whatsapp-telefono.md`](recepcionista-ia-whatsapp-telefono.md).

## Stack Técnico

- **FastAPI** (Python) — Orquestador de conversación + motor de reservas.
- **PostgreSQL** — Base de datos principal (multi-tenant).
- **Redis** — Caché / estado de conversaciones activas y broker para Celery.
- **Claude Haiku 4.5** — LLM del agente, vía tool-calling.
- **360dialog / Meta Cloud API** — WhatsApp Business API.
- **Twilio** — Canal de voz (TwiML para flujos estándar y Media Streams para streaming).
- **Deepgram** — Speech-to-Text (STT) en tiempo real.
- **ElevenLabs** — Text-to-Speech (TTS) en streaming.
- **Qdrant** — Base de datos vectorial para FAQs (RAG).
- **OpenAI** — Generación de embeddings para la base de conocimientos.

## Estado de Implementación

El backend está implementado y funcional en sus núcleos principales:
- **Motor de Reservas**: Gestión completa de disponibilidad, asignación de mesas y clientes.
- **Orquestador de IA**: Integración con Claude Haiku 4.5 y ejecución de tools.
- **Canales**: Webhook de WhatsApp y flujo de voz Twilio (TwiML).
- **Voz Avanzada**: Implementación de streaming de medios (STT Deepgram / TTS ElevenLabs), actualmente en estado **PARCIAL** (pendiente de optimización del bucle de streaming).
- **Soporte de Conocimientos**: Sistema de RAG implementado sobre Qdrant para responder FAQs.
- **Automatización**: Worker de recordatorios programados con Celery.
- **Seguridad**: Autenticación JWT RS256 para comunicación con el panel de control.

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
cp .env.example .env   # y rellenar los valores (incluyendo keys de Deepgram, ElevenLabs, Qdrant y OpenAI)

# 5. Comprobar lint y tests
ruff check .
pytest
```

> Nota: Redis NO lo gestiona Laragon; se arranca manualmente por el
> desarrollador (p. ej. `redis-server`). PostgreSQL sí lo gestiona Laragon.

## Base de datos

La conexión se configura con `DATABASE_URL` en `.env`:
`DATABASE_URL=postgresql+asyncpg://usuario:password@localhost:5432/agente_whatsapp`

- **UUIDs**: Se generan en PostgreSQL (`gen_random_uuid()`) para compatibilidad entre FastAPI y Laravel.
- **Migraciones**: Gestionadas con Alembic.
- **Enums**: Modelados como `VARCHAR` + `CHECK` para evitar problemas de autogeneración en Alembic.

## Estructura del Proyecto

```
app/               # aplicación FastAPI (monolito modular / vertical slices)
├── core/          # Configuración, seguridad, STT, TTS, VectorStore, Embeddings
├── modules/       # Módulos de dominio (reservations, availability, customers, reminders, faqs)
├── agent/         # Orquestador del agente LLM + tools
├── channels/      # Adaptadores de transporte (whatsapp, voice)
└── db/            # Sesión de base de datos (SQLAlchemy)
tests/             # Suite de tests (pytest), espejo de la estructura de app/
docs/              # Documentación técnica y guías de setup
```
