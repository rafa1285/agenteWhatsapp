# Plan de Pruebas para el Flujo Completo de WhatsApp → App → Panel

## Objetivo
Verificar el flujo completo: envío de mensaje por WhatsApp → procesamiento por la app (FastAPI) → creación de reserva → visualización en el panel de control (Laravel).

## Prerrequisitos
1. Docker y Docker Compose instalados
2. Variables de entorno configuradas (ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, etc.)
3. Llaves JWT generadas en ambos repositorios

## Arquitectura de Pruebas
Utilizaremos el `docker-compose.integration.yml` que incluye:
- PostgreSQL, Redis, Backend (FastAPI) y Panel (Laravel).

## Fase 1: Preparación del Entorno
(Pasos de generación de llaves JWT y configuración de `.env` según especificado en el README).

## Fase 2: Levantar Servicios de Integración
`docker compose -f agenteWhatsapp/docker-compose.integration.yml up -d`

## Fase 3: Ejecutar Pruebas Automatizadas
### 3.1 Pruebas del Backend
`python -m pytest tests/ -v`

### 3.2 Pruebas de Canales
- **WhatsApp**: `python -m pytest tests/channels/whatsapp/ -v`
- **Voz (TwiML)**: `python -m pytest tests/channels/voice/ -v`

## Fase 4: Prueba Manual End-to-End (WhatsApp)
1. **Obtener token JWT** válido desde el panel.
2. **Simular mensaje** mediante `curl` al endpoint `/api/whatsapp/webhook`.
3. **Verificar respuesta** (`{"status": "ok"}`).
4. **Verificar DB**: Consultar tablas `customers`, `reservations` y `conversations`.
5. **Verificar Panel**: Confirmar que la reserva aparece en la sección de Reservas.

## Fase 5: Pruebas de Flujos Específicos
- **Reserva completa**: Verificación de extracción de entidades y confirmación.
- **Modificación/Cancelación**: Flujo de localización de reserva y actualización.
- **Consultas FAQ**: Verificación de respuestas basadas en RAG (Qdrant).
- **Llamada de Voz (TwiML)**: Prueba real llamando al número Twilio -> Saludo -> Reserva -> Confirmación WhatsApp.

## Fase 6: Pruebas de Voz en Tiempo Real (Media Streams)
1. `USE_MEDIA_STREAMS=true` en `.env` (la URL del WebSocket se deriva de
   `VOICE_BASE_URL`; no hay otra variable que poner).
2. Iniciar llamada y verificar en el log el `start` del Media Stream
   (`streamSid=...`) y la conexión de Deepgram.
3. Verificar transcripción en tiempo real (Deepgram) y respuesta hablada por
   frases (ElevenLabs). El log marca "primera frase a los N ms" y "primer byte de
   audio a los N ms".
4. Testear **Barge-in**: interrumpir al agente y verificar que el audio se detiene
   al instante (`barge-in: se corta el audio en curso`).

## Fase 7: Limpiar y Reiniciar
`docker compose -f agenteWhatsapp/docker-compose.integration.yml down -v`
