# Configuración de Twilio para el canal de voz

Guía operativa para recibir llamadas reales y crear reservas por voz
con el backend implementado en `app/channels/voice/`.

## Requisitos

- Backend FastAPI en marcha.
- PostgreSQL con al menos un restaurante activo y `voice_number` en E.164.
- Cuenta Twilio con un número con capacidad **Voice**.
- URL pública HTTPS (ngrok, cloudflared o dominio).
- WhatsApp configurado para confirmaciones escritas.

## Variables de Entorno (`.env`)

```dotenv
VOICE_BASE_URL=https://tu-tunel-o-dominio.example
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=tu_auth_token
TWILIO_VALIDATE_SIGNATURE=true

# Voz en tiempo real (Media Streams). La URL del WebSocket NO se configura:
# se deriva de VOICE_BASE_URL (https -> wss) y lleva el CallSid.
USE_MEDIA_STREAMS=false      # Cambiar a true para usar Deepgram/ElevenLabs
DEEPGRAM_API_KEY=tu_key
ELEVENLABS_API_KEY=tu_key
VOICE_STT_MODEL=nova-3
VOICE_STT_LANGUAGE=es
VOICE_STT_END_OF_TURN_MS=700  # silencio que cierra el turno del hablante
VOICE_TTS_MODEL=eleven_flash_v2_5
VOICE_TTS_VOICE_ID=EXAVITQu4vr4xnSDxMaL
```

## Modos de Operación

El backend soporta dos modos de interacción de voz:

### 1. Flujo Estándar (TwiML por turnos)
Es el modo por defecto (`USE_MEDIA_STREAMS=false`). Twilio gestiona el STT y el
TTS nativamente y cada turno es un POST al Voice URL.
- **Voice URL**: `POST {VOICE_BASE_URL}/api/voice/call`
- **Status Callback**: `POST {VOICE_BASE_URL}/api/voice/status`
- **Ventajas**: Configuración simple, alta estabilidad, y es el único modo que
  hace transferencia en vivo (`<Dial>`).
- **Coste**: voz robótica de `<Say>` y un silencio de varios segundos por turno
  (Twilio cierra el speech, hace el POST, espera al LLM y sintetiza).

### 2. Flujo en tiempo real (Media Streams)
Con `USE_MEDIA_STREAMS=true` el saludo responde con
`<Connect><Stream url="wss://.../api/voice/stream?CallSid=..."/></Connect>`.
Todo lo demás pasa por el WebSocket:

- **Stack**: audio μ-law 8 kHz de Twilio → Deepgram (STT streaming) → turno
  cerrado → orquestador en streaming (`run_conversation_stream`) → frases →
  ElevenLabs `flash` en μ-law 8 kHz → Twilio.
- Se habla frase a frase mientras el modelo todavía escribe, y el barge-in
  (`SpeechStarted` de Deepgram) manda `clear` a Twilio para cortar el audio.
- El `<Say>` que va detrás del `<Connect>` solo suena si el WebSocket cae: es el
  respaldo para que el cliente no se quede en silencio.
- **Identidad**: el WebSocket resuelve tenant y cliente en `voice_calls` por su
  `CallSid` (lo creó el primer POST). No se pasa el `restaurant_id` por la URL.
- **Limitación**: dentro de un Media Stream Twilio no ejecuta TwiML nuevo, así
  que la transferencia en vivo no está disponible en este modo. La escalación
  deja su fila en `escalations` para que actúe el panel.
- **Latencia**: se registran en el log el primer byte de TTS, la primera frase
  tras el turno y el primer audio del turno, en ms.

## Pasos en Twilio Console

1. **Configuración del Número**:
   - **A call comes in** → Webhook → `POST {VOICE_BASE_URL}/api/voice/call`
   - **Call status changes** → Webhook → `POST {VOICE_BASE_URL}/api/voice/status`
2. **Vincular al Restaurante**: `Restaurant.voice_number` debe coincidir con el número de Twilio en formato E.164.

## Checklist de Prueba

1. Llamas al número Twilio (`python test_call.py` desde otro terminal).
2. Oyes el saludo + aviso de grabación (RGPD). En modo stream lo dice ElevenLabs.
3. Hablas → el backend resuelve el turno y responde. En modo stream no hay
   POST por turno: todo va por el WebSocket.
4. Interrumpe al agente a mitad de frase → debe callar enseguida (barge-in).
5. Confirmas reserva → se envía la confirmación por WhatsApp y se cuelga.
6. Status Callback → la llamada queda como `completed` en `voice_calls`.

## Seguridad

- La validación de `X-Twilio-Signature` es obligatoria en `/call` y `/status` mediante `TWILIO_AUTH_TOKEN`.
- El endpoint `/stream` (WebSocket) no valida la firma: Twilio no firma el
  handshake. Solo acepta CallSid existentes en `voice_calls`, así que una
  conexión ajena se cierra con 4004 sin tocar datos de otro tenant.

