# Hoja de ruta de implementación

## Fases de Desarrollo

| Fase | Descripción | Estado |
|---|---|---|
| 0 | Fundamentos: CLAUDE.md, Skills, Linters, CI básico | COMPLETADO |
| 1 | Estructura FastAPI + modelos SQLAlchemy (sección 7) | COMPLETADO |
| 2 | Motor de reservas (funciones puras) con tests | COMPLETADO |
| 3 | Cliente Claude Haiku 4.5 + definición de tools | COMPLETADO |
| 4 | Orquestador de conversación (LLM + tools + memoria) | COMPLETADO |
| 5 | Webhook WhatsApp (360dialog) + prueba E2E | COMPLETADO |
| 6 | Canal de voz (TwiML + STT/TTS nativo) | COMPLETADO |
| 6.1 | Canal de voz (Streaming: Deepgram, ElevenLabs) | PARCIAL |
| 6.2 | Knowledge Base (RAG: Qdrant + OpenAI) | COMPLETADO |
| 7 | Recordatorios automáticos (Worker Celery + Redis) | COMPLETADO |
| 8 | Panel web Laravel + Livewire (Diseño minimalista) | PENDIENTE |
| 9 | Integración conjunta + CI/CD completo | PENDIENTE |
| 10 | Piloto real (Er Pichi de Cai) | PENDIENTE |
| 11 | Productización multi-cliente | PENDIENTE |

## Skills del Proyecto
- `backend-conventions`: Patrones FastAPI async, SQLAlchemy, multi-tenant.
- `testing-standards`: pytest/TDD para motor de reservas y canales.
- `panel-frontend-design`: Sistema de diseño Livewire + Tailwind.
- `rgpd-security`: Checklist de privacidad y seguridad.
