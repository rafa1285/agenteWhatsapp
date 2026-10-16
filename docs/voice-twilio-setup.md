# Configuración de Twilio para el canal de voz

Guía operativa para recibir llamadas reales y crear reservas por voz
con el backend ya implementado en `app/channels/voice/`.

## Requisitos

- Backend FastAPI en marcha (`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`).
- PostgreSQL con al menos un restaurante activo y `voice_number` en E.164.
- Cuenta Twilio con un número con capacidad **Voice**.
- URL pública HTTPS (ngrok, cloudflared o dominio de staging/producción).
- WhatsApp configurado si quieres la confirmación escrita tras la reserva.

## Variables de entorno

En `.env` (nunca en git):

```dotenv
VOICE_BASE_URL=https://tu-tunel-o-dominio.example
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=tu_auth_token
TWILIO_VALIDATE_SIGNATURE=true
```

Notas:

- `VOICE_BASE_URL` debe ser exactamente la URL pública que Twilio usa
  (sin barra final). El backend la usa para firmar/validar y para los
  `action` de `<Gather>` / `<Dial>`.
- `TWILIO_AUTH_TOKEN` habilita la validación de `X-Twilio-Signature` en
  `POST /api/voice/call` y `POST /api/voice/status`.
- En tests el flag `TESTING=true` desactiva la validación de firma.

## Endpoints del backend

| Uso Twilio | Método | URL |
|---|---|---|
| A call comes in (Voice URL) | `POST` | `{VOICE_BASE_URL}/api/voice/call` |
| Call status changes | `POST` | `{VOICE_BASE_URL}/api/voice/status` |

## Pasos en Twilio Console

1. Compra o elige un número con Voice.
2. En el número → **Voice & Fax**:
   - **A call comes in** → Webhook → `POST {VOICE_BASE_URL}/api/voice/call`
   - **Call status changes** → Webhook → `POST {VOICE_BASE_URL}/api/voice/status`
3. (Opcional) Activa grabación de llamadas en la consola del número para
   que el status callback traiga `RecordingUrl` (el saludo ya avisa de
   grabación por RGPD).
4. Si usas cuenta trial: verifica el móvil desde el que vas a llamar.

## Vincular el número al restaurante

`Restaurant.voice_number` debe coincidir **exactamente** con el `To`
que envía Twilio (E.164), por ejemplo `+34911234567`.

Ejemplo SQL:

```sql
UPDATE restaurants
SET voice_number = '+34911234567',
    active = true
WHERE id = '<restaurant-id>';
```

## Desarrollo local con túnel

```bash
# terminal 1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# terminal 2
ngrok http 8000
```

Copia la URL HTTPS de ngrok a `VOICE_BASE_URL`, reinicia uvicorn si
hace falta y actualiza los webhooks del número en Twilio.

## Checklist de prueba

1. Llamas al número Twilio.
2. Oyes el saludo + aviso de grabación.
3. Hablas (p. ej. “Quiero reservar para dos mañana a las dos”).
4. El backend crea `voice_calls` y, si procede, `reservations` con
   `source_channel = voice`.
5. Tras confirmar, cuelga y envía confirmación por WhatsApp al `From`.
6. El status callback marca la llamada como `completed` y, si hay
   grabación, rellena `recording_url`.

## Seguridad

- Con `TWILIO_AUTH_TOKEN` configurado, las peticiones sin firma válida
  no procesan la llamada: `/call` responde TwiML de cortesía y `/status`
  es no-op (HTTP 200 para no provocar reintentos).
- No commitees el Auth Token. Usa solo `.env` local o secretos del entorno.

## Fuera de esta guía

- Integración ElevenLabs (STT/TTS externo).
- Control fino de grabación vía TwiML `<Record>`.
- Números Twilio distintos por restaurante (hoy se asume una cuenta
  Twilio compartida y un `voice_number` por tenant).
