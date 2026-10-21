"""Configuración de la aplicación (pydantic-settings), leída de `.env` / entorno."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes de la aplicación (leídos de `.env` / entorno)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Driver obligatorio: postgresql+asyncpg (validado en app/db/session.py).
    # Default placeholder para desarrollo local; el valor real se define en `.env`
    # (ver `.env.example`). Nunca guardar credenciales reales en el código.
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/agente_whatsapp"

    # Cliente LLM (Anthropic / Claude Haiku 4.5). La API key se lee de `.env`;
    # si es None/"" el SDK intenta leer `ANTHROPIC_API_KEY` del entorno.
    # Prefijo AGENT_ (no ANTHROPIC_) para los no-secretos: Claude Code define
    # `ANTHROPIC_MODEL` en su entorno y colisionaria con el campo.
    ANTHROPIC_API_KEY: str | None = None
    AGENT_MODEL: str = "claude-haiku-4-5-20251001"
    AGENT_MAX_TOKENS: int = 1024
    AGENT_TEMPERATURE: float = 0.3

    # Canal WhatsApp (Meta Cloud API o 360dialog). El token es secreto y se define en `.env`;
    # el verify token protege el handshake del webhook (producción lo fija).
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = "cambia-me"
    WHATSAPP_API_URL: str = "https://graph.facebook.com/v19.0"
    WHATSAPP_API_TOKEN: str | None = None
    WHATSAPP_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_API_TIMEOUT: float = 10.0

    # Canal de voz (webhook Twilio, TwiML sin SDK). `VOICE_BASE_URL` es la base
    # pública de los webhooks (túnel local / dominio): Twilio exige URLs
    # absolutas en los `action` de Gather/Dial. No es secreto; se fija en `.env`.
    VOICE_BASE_URL: str = "https://example.com"
    # Credenciales y validación del webhook Twilio. `TWILIO_AUTH_TOKEN` debe
    # configurarse en `.env` para validar `X-Twilio-Signature`; si está vacío,
    # el backend no valida la firma. La validación también puede desactivarse
    # en tests o entornos controlados con `TWILIO_VALIDATE_SIGNATURE=false`.
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_VALIDATE_SIGNATURE: bool = True
    VOICE_STT_CONFIDENCE_THRESHOLD: float = 0.5
    VOICE_SILENCE_REPROMPT_SECONDS: int = 4
    VOICE_SILENCE_HANGUP_SECONDS: int = 8
    VOICE_TRANSFER_DIAL_TIMEOUT: int = 15

    # Worker de recordatorios (Celery + Redis beat). Celery reutiliza `REDIS_URL`
    # como broker y result backend; el resto de variables rigen el tick del
    # worker de recordatorios (revisa los PENDING vencidos cada pocos minutos).
    REDIS_URL: str = "redis://localhost:6379/0"
    REMINDER_TICK_INTERVAL_SECONDS: int = 300
    REMINDER_MAX_ATTEMPTS: int = 3  # 1 envío + 2 reintentos
    REMINDER_RETRY_DELAY_SECONDS: int = 300
    REMINDER_BATCH_SIZE: int = 50

    # JWT Auth (panel → backend). Clave pública PEM para validar RS256.
    # En dev: archivo local; en prod: secret manager / volume montado.
    JWT_PUBLIC_KEY_PATH: str = "storage/keys/public.pem"
    JWT_ISSUER: str = "reception-panel"
    JWT_AUDIENCE: str = "reception-api"
    JWT_ALGORITHM: str = "RS256"

    # Webhook callbacks: backend → panel (real-time sync de reservas, recordatorios, escalaciones).
    # En dev puede estar vacío (polling). En prod se fija la URL del panel + secreto HMAC.
    PANEL_WEBHOOK_URL: str = ""
    PANEL_WEBHOOK_SECRET: str = ""

    # Knowledge Base (Qdrant + Embeddings).
    # Dos modos excluyentes: con `QDRANT_PATH` no vacio Qdrant corre embebido en
    # el proceso (ficheros locales; solo desarrollo / un unico worker). Si no, se
    # conecta al servidor de `QDRANT_URL` (`http://localhost:6333` en dev).
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_PATH: str = ""
    QDRANT_API_KEY: str | None = None
    # FastEmbed: modelo ONNX local, sin API keys ni coste. Debe ser multilingue
    # porque las preguntas llegan en espanol. `EMBEDDING_DIM` tiene que coincidir
    # con la dimension del modelo y con la coleccion creada en Qdrant.
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM: int = 384
    EMBEDDING_CACHE_DIR: str = "storage/models"
    # Score de similitud minima para aceptar una FAQ recuperada por RAG. Con
    # parrafos lejanos ("¿a qué hora abren?" vs "abre de 13:00 a 23:00") este
    # modelo ronda 0.6; por debajo del umbral se deriva a un humano.
    FAQ_RAG_SCORE_THRESHOLD: float = 0.45

    # Deepgram (STT en tiempo real del Media Stream). El audio de Twilio llega en
    # μ-law 8 kHz, formato que fija el `encoding`/`sample_rate` de la conexión.
    DEEPGRAM_API_KEY: str | None = None
    VOICE_STT_MODEL: str = "nova-3"
    VOICE_STT_LANGUAGE: str = "es"
    # Con `dictation` Deepgram devuelve frases finales por separado y no acepta
    # `utterance_end_ms` en este modelo, así que el fin de turno se decide aquí:
    # si transcurre este silencio (ms) sin nuevas frases, el turno se da por
    # cerrado. Bajo = respuestas ágiles pero corta las frases pausadas.
    VOICE_STT_END_OF_TURN_MS: int = 700

    # ElevenLabs (TTS en tiempo real). `flash` es la familia de baja latencia para
    # teléfono; `multilingual_v2` suena mejor pero tarda demasiado en responder.
    ELEVENLABS_API_KEY: str | None = None
    VOICE_TTS_MODEL: str = "eleven_flash_v2_5"
    VOICE_TTS_VOICE_ID: str = "EXAVITQu4vr4xnSDxMaL"

    # Voz en tiempo real: `<Connect><Stream>` en vez de `<Say>`/`<Gather>` por
    # turnos. La URL del WebSocket se deriva de `VOICE_BASE_URL` (https -> wss) y
    # no se configura aparte, para que túnel y dominio sean una sola verdad.
    USE_MEDIA_STREAMS: bool = False

    # Testing flag para deshabilitar webhooks y otras integraciones externas en tests
    TESTING: bool = False


@lru_cache
def get_settings() -> Settings:
    """Instancia única de Settings (cacheada para tests y rendimiento)."""
    return Settings()


settings = get_settings()
