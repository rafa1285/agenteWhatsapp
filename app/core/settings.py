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

    # Canal WhatsApp (360dialog). El token es secreto y se define en `.env`;
    # el verify token protege el handshake del webhook (producción lo fija).
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = "cambia-me"
    WHATSAPP_API_URL: str = "https://waba.360dialog.io/v1/messages"
    WHATSAPP_API_TOKEN: str | None = None
    WHATSAPP_API_TIMEOUT: float = 10.0

    # Canal de voz (webhook Twilio, TwiML sin SDK). `VOICE_BASE_URL` es la base
    # pública de los webhooks (túnel local / dominio): Twilio exige URLs
    # absolutas en los `action` de Gather/Dial. No es secreto; se fija en `.env`.
    VOICE_BASE_URL: str = "https://example.com"
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

    # Testing flag para deshabilitar webhooks y otras integraciones externas en tests
    TESTING: bool = False


@lru_cache
def get_settings() -> Settings:
    """Instancia única de Settings (cacheada para tests y rendimiento)."""
    return Settings()


settings = get_settings()
